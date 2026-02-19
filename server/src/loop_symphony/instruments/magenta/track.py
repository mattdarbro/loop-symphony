"""Track instrument — stage 4 of the Magenta Loop.

Evaluates past prescriptions by comparing original vs follow-up content,
and feeds learned patterns into the knowledge system.
"""

import json
import logging

from loop_symphony.db.client import DatabaseClient
from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext
from loop_symphony.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)


class TrackInstrument(BaseInstrument):
    """Evaluate past prescriptions and feed learning into knowledge system."""

    name = "magenta_track"
    max_iterations = 1
    required_capabilities = frozenset({"reasoning"})

    def __init__(
        self,
        *,
        claude: ClaudeClient | None = None,
        db: DatabaseClient | None = None,
    ) -> None:
        self.claude = claude if claude is not None else ClaudeClient()
        self.db = db if db is not None else DatabaseClient()

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        logger.info("Magenta track starting")

        creator_id = self._extract_creator_id(context)

        # Find applied prescriptions with follow-up content
        applied: list[dict] = []
        try:
            if creator_id:
                applied = await self.db.get_applied_prescriptions_with_followups(
                    creator_id
                )
        except Exception as exc:
            logger.warning(f"DB fetch failed (non-fatal): {exc}")

        if not applied:
            return InstrumentResult(
                outcome=Outcome.COMPLETE,
                findings=[Finding(
                    content="Nothing to track — no applied prescriptions with follow-up content.",
                    source="magenta_track",
                    confidence=1.0,
                )],
                summary="Nothing to track — no applied prescriptions with follow-up content.",
                confidence=1.0,
                iterations=1,
                sources_consulted=["content_prescriptions_db"],
            )

        # For each applied prescription, fetch original and follow-up metrics
        evaluations: list[dict] = []
        for rx in applied:
            original_id = rx.get("content_id")
            followup_id = rx.get("followup_content_id")
            if not original_id or not followup_id:
                continue

            original_content: list[dict] = []
            followup_content: list[dict] = []
            try:
                orig_results = await self.db.list_creator_content(
                    creator_id, limit=50
                )
                original_content = [
                    c for c in orig_results if c.get("content_id") == original_id
                ]
                followup_content = [
                    c for c in orig_results if c.get("content_id") == followup_id
                ]
            except Exception as exc:
                logger.warning(f"Content fetch failed (non-fatal): {exc}")

            evaluations.append({
                "prescription": rx,
                "original": original_content[0] if original_content else None,
                "followup": followup_content[0] if followup_content else None,
            })

        # Evaluate via Claude
        prompt = self._build_evaluation_prompt(evaluations)
        system = (
            "You are evaluating whether content prescriptions were effective.\n"
            "Compare original content metrics to follow-up content metrics.\n"
            "Score effectiveness 0.0-1.0 and explain what worked or didn't.\n\n"
            "Output valid JSON: a list of objects with keys:\n"
            "prescription_id, effectiveness_score (0.0-1.0), summary, "
            "learned_pattern (string describing the pattern, or null), "
            "is_effective (bool — true if score >= 0.5)."
        )

        response = await self.claude.complete(prompt, system=system)

        # Update prescriptions and feed knowledge system
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

                    # Feed into knowledge system via DB
                    pattern = r.get("learned_pattern")
                    if pattern and creator_id:
                        await self._store_learning(
                            creator_id=creator_id,
                            pattern=pattern,
                            is_effective=r.get("is_effective", False),
                            context=context,
                        )
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(f"Tracking update failed (non-fatal): {exc}")

        finding = Finding(
            content=response,
            source="magenta_track",
            confidence=0.8,
        )

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response,
            confidence=0.8,
            iterations=1,
            sources_consulted=["content_prescriptions_db", "content_performance_db", "claude"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    async def _store_learning(
        self,
        creator_id: str,
        pattern: str,
        is_effective: bool,
        context: TaskContext | None,
    ) -> None:
        """Store a learned pattern as a knowledge entry."""
        from loop_symphony.models.knowledge import KnowledgeCategory, KnowledgeSource

        category = (
            KnowledgeCategory.PATTERNS if is_effective
            else KnowledgeCategory.BOUNDARIES
        )
        entry = {
            "category": category.value,
            "title": f"Magenta learning for {creator_id}",
            "content": pattern,
            "source": KnowledgeSource.MAGENTA_TRACKER.value,
            "confidence": 0.7,
            "tags": json.dumps(["magenta", "content_analytics", creator_id]),
            "is_active": True,
        }
        try:
            from loop_symphony.db.client import DatabaseClient as _DB
            db = self.db
            await db.create_knowledge_entry(entry)
        except Exception as exc:
            logger.warning(f"Knowledge entry creation failed (non-fatal): {exc}")

    @staticmethod
    def _build_evaluation_prompt(evaluations: list[dict]) -> str:
        return f"Prescription evaluations to assess:\n{json.dumps(evaluations, indent=2, default=str)}"
