"""Track instrument — stage 4 of the Magenta Loop."""

import json
import logging
from typing import Any

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)


class TrackInstrument(BaseInstrument):
    """Evaluate past prescriptions and feed learning into knowledge system."""

    name = "magenta_track"
    max_iterations = 1
    required_capabilities = frozenset({"reasoning"})

    def __init__(self, *, claude: ClaudeClient | None = None, db: Any = None) -> None:
        self.claude = claude if claude is not None else ClaudeClient()
        self.db = db

    async def execute(self, query: str, context: TaskContext | None = None) -> InstrumentResult:
        logger.info("Magenta track starting")

        creator_id = self._extract_creator_id(context)

        applied: list[dict] = []
        if self.db is not None:
            try:
                if creator_id:
                    applied = await self.db.get_applied_prescriptions_with_followups(creator_id)
            except Exception as exc:
                logger.warning(f"DB fetch failed (non-fatal): {exc}")

        if not applied:
            return InstrumentResult(
                outcome=Outcome.COMPLETE,
                findings=[Finding(
                    content="Nothing to track — no applied prescriptions with follow-up content.",
                    source="magenta_track", confidence=1.0,
                )],
                summary="Nothing to track — no applied prescriptions with follow-up content.",
                confidence=1.0, iterations=1,
                sources_consulted=["content_prescriptions_db"],
            )

        evaluations: list[dict] = []
        for rx in applied:
            original_id = rx.get("content_id")
            followup_id = rx.get("followup_content_id")
            if not original_id or not followup_id:
                continue
            original_content: list[dict] = []
            followup_content: list[dict] = []
            if self.db is not None:
                try:
                    orig_results = await self.db.list_creator_content(creator_id, limit=50)
                    original_content = [c for c in orig_results if c.get("content_id") == original_id]
                    followup_content = [c for c in orig_results if c.get("content_id") == followup_id]
                except Exception as exc:
                    logger.warning(f"Content fetch failed (non-fatal): {exc}")

            evaluations.append({
                "prescription": rx,
                "original": original_content[0] if original_content else None,
                "followup": followup_content[0] if followup_content else None,
            })

        prompt = self._build_evaluation_prompt(evaluations)
        system = (
            "You are evaluating whether content prescriptions were effective.\n"
            "Output valid JSON: a list of objects with keys:\n"
            "prescription_id, effectiveness_score (0.0-1.0), summary, "
            "learned_pattern (string or null), is_effective (bool)."
        )

        response = await self.claude.complete(prompt, system=system)

        if self.db is not None:
            try:
                results = json.loads(response) if isinstance(response, str) else response
                if isinstance(results, list):
                    for r in results:
                        rx_id = r.get("prescription_id")
                        if rx_id:
                            await self.db.update_prescription(rx_id, {
                                "status": "evaluated",
                                "effectiveness_score": r.get("effectiveness_score", 0.0),
                            })
            except (json.JSONDecodeError, Exception) as exc:
                logger.warning(f"Tracking update failed (non-fatal): {exc}")

        finding = Finding(content=response, source="magenta_track", confidence=0.8)

        return InstrumentResult(
            outcome=Outcome.COMPLETE, findings=[finding], summary=response,
            confidence=0.8, iterations=1,
            sources_consulted=["content_prescriptions_db", "content_performance_db", "claude"],
        )

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
    def _build_evaluation_prompt(evaluations: list[dict]) -> str:
        return f"Prescription evaluations to assess:\n{json.dumps(evaluations, indent=2, default=str)}"
