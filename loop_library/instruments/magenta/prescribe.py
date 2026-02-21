"""Prescribe instrument — stage 3 of the Magenta Loop."""

import json
import logging
from typing import Any
from uuid import uuid4

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)


class PrescribeInstrument(BaseInstrument):
    """Generate actionable prescriptions from diagnoses."""

    name = "magenta_prescribe"
    max_iterations = 1
    required_capabilities = frozenset({"reasoning"})

    def __init__(self, *, claude: ClaudeClient | None = None, db: Any = None) -> None:
        self.claude = claude if claude is not None else ClaudeClient()
        self.db = db

    async def execute(self, query: str, context: TaskContext | None = None) -> InstrumentResult:
        logger.info("Magenta prescribe starting")

        diagnose_output = self._get_previous_output(context)
        if diagnose_output is None:
            return InstrumentResult(
                outcome=Outcome.INCONCLUSIVE, findings=[], summary="No diagnosis data available.",
                confidence=0.0, iterations=1, sources_consulted=[],
            )

        creator_id = self._extract_creator_id(context)

        top_content: list[dict] = []
        past_prescriptions: list[dict] = []
        if self.db is not None:
            try:
                if creator_id:
                    top_content = await self.db.get_top_performing_content(creator_id, limit=5)
                    past_prescriptions = await self.db.list_prescriptions(creator_id, status="evaluated")
            except Exception as exc:
                logger.warning(f"DB fetch failed (non-fatal): {exc}")

        prompt = self._build_prompt(diagnose_output, top_content, past_prescriptions)
        system = (
            "You are a YouTube growth strategist. Based on the diagnoses, generate "
            "specific, actionable prescriptions.\n"
            "Output valid JSON: a list of prescription objects."
        )

        response = await self.claude.complete(prompt, system=system)

        if self.db is not None:
            app_id = context.app_id if context else None
            try:
                prescriptions = json.loads(response) if isinstance(response, str) else response
                if isinstance(prescriptions, list):
                    for rx in prescriptions:
                        record = {
                            "id": str(uuid4()),
                            "app_id": app_id,
                            "creator_id": creator_id or "unknown",
                            "content_id": rx.get("content_id", "unknown"),
                            "diagnosis_type": rx.get("diagnosis_type", ""),
                            "title": rx.get("title", ""),
                            "description": rx.get("description", ""),
                            "specific_action": rx.get("specific_action", ""),
                            "reference_content_id": rx.get("reference_content_id"),
                            "status": "pending",
                        }
                        await self.db.create_prescription(record)
            except (json.JSONDecodeError, Exception) as exc:
                logger.warning(f"Prescription storage failed (non-fatal): {exc}")

        finding = Finding(content=response, source="magenta_prescribe", confidence=0.8)

        return InstrumentResult(
            outcome=Outcome.COMPLETE, findings=[finding], summary=response,
            confidence=0.8, iterations=1,
            sources_consulted=["content_performance_db", "content_prescriptions_db", "claude"],
        )

    @staticmethod
    def _get_previous_output(context: TaskContext | None) -> dict | None:
        if context is None or not context.input_results:
            return None
        prev = context.input_results[0]
        return prev if isinstance(prev, dict) else None

    @staticmethod
    def _extract_creator_id(context: TaskContext | None) -> str | None:
        if context is None or not context.input_results:
            return None
        for result in (context.input_results or []):
            if isinstance(result, dict):
                for finding in result.get("findings", []):
                    content = finding.get("content", "")
                    if isinstance(content, str) and "creator_id" in content:
                        try:
                            parsed = json.loads(content)
                            if "creator_id" in parsed:
                                return parsed["creator_id"]
                        except (json.JSONDecodeError, TypeError):
                            pass
        return None

    @staticmethod
    def _build_prompt(diagnose_output: dict, top_content: list[dict], past_prescriptions: list[dict]) -> str:
        parts = [f"Diagnoses:\n{json.dumps(diagnose_output, indent=2, default=str)}"]
        if top_content:
            top_summary = [
                {"content_id": c.get("content_id"), "title": c.get("title"),
                 "views": c.get("views"), "avg_view_percentage": c.get("avg_view_percentage")}
                for c in top_content
            ]
            parts.append(f"\nTop performing content:\n{json.dumps(top_summary, indent=2)}")
        if past_prescriptions:
            effective = [p for p in past_prescriptions if (p.get("effectiveness_score") or 0) > 0.5]
            if effective:
                parts.append(f"\nPast effective prescriptions ({len(effective)}):\n{json.dumps(effective[:5], indent=2, default=str)}")
        return "\n".join(parts)
