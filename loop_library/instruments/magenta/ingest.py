"""Ingest instrument — stage 1 of the Magenta Loop.

Extracts raw analytics from context, validates, and summarises trends.
DB storage is optional — inject a db object or it's skipped.
"""

import json
import logging
from typing import Any, Protocol, runtime_checkable

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {"content_id", "creator_id", "views"}


@runtime_checkable
class ContentDB(Protocol):
    """Protocol for Magenta content database operations."""
    async def upsert_content_performance(self, record: dict) -> None: ...
    async def list_creator_content(self, creator_id: str, limit: int = 20) -> list[dict]: ...


class IngestInstrument(BaseInstrument):
    """Ingest raw analytics data and summarise trends."""

    name = "magenta_ingest"
    max_iterations = 1
    required_capabilities = frozenset({"reasoning"})

    def __init__(
        self,
        *,
        claude: ClaudeClient | None = None,
        db: Any = None,
    ) -> None:
        self.claude = claude if claude is not None else ClaudeClient()
        self.db = db

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        logger.info("Magenta ingest starting")

        raw = self._extract_analytics(context)
        if raw is None:
            return InstrumentResult(
                outcome=Outcome.INCONCLUSIVE,
                findings=[],
                summary="No analytics data provided in input_results.",
                confidence=0.0,
                iterations=1,
                sources_consulted=[],
            )

        missing = _REQUIRED_FIELDS - set(raw.keys())
        if missing:
            return InstrumentResult(
                outcome=Outcome.INCONCLUSIVE,
                findings=[],
                summary=f"Missing required fields: {', '.join(sorted(missing))}",
                confidence=0.0,
                iterations=1,
                sources_consulted=[],
            )

        # Store in DB if available
        if self.db is not None:
            try:
                await self.db.upsert_content_performance(raw)
            except Exception as exc:
                logger.warning(f"DB upsert failed (non-fatal): {exc}")

        # Fetch history if DB available
        history: list[dict] = []
        creator_id = raw.get("creator_id", "")
        if self.db is not None:
            try:
                history = await self.db.list_creator_content(creator_id, limit=20)
            except Exception as exc:
                logger.warning(f"History fetch failed (non-fatal): {exc}")

        # Summarise via Claude
        prompt = self._build_summary_prompt(raw, history)
        system = (
            "You are a YouTube analytics expert. Summarise the current "
            "content's performance compared to the creator's recent history. "
            "Be specific with numbers. Output JSON with keys: "
            "summary, trends (list[str]), notable_changes (list[str])."
        )

        response = await self.claude.complete(prompt, system=system)

        finding = Finding(content=response, source="magenta_ingest", confidence=0.9)

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response,
            confidence=0.9,
            iterations=1,
            sources_consulted=["content_performance_db", "claude"],
        )

    @staticmethod
    def _extract_analytics(context: TaskContext | None) -> dict | None:
        if context is None or not context.input_results:
            return None
        first = context.input_results[0]
        if isinstance(first, dict):
            return first.get("analytics", first)
        return None

    @staticmethod
    def _build_summary_prompt(metrics: dict, history: list[dict]) -> str:
        current = {
            "content_id": metrics.get("content_id"),
            "title": metrics.get("title"),
            "views": metrics.get("views"),
            "likes": metrics.get("likes"),
            "comments": metrics.get("comments"),
            "avg_view_percentage": metrics.get("avg_view_percentage"),
            "impressions": metrics.get("impressions"),
            "ctr": metrics.get("impression_click_through_rate"),
            "subscriber_count": metrics.get("subscriber_count"),
        }
        hist_summary = [
            {
                "content_id": h.get("content_id"),
                "title": h.get("title"),
                "views": h.get("views"),
                "avg_view_percentage": h.get("avg_view_percentage"),
            }
            for h in history[:10]
        ]
        return (
            f"Current content metrics:\n{json.dumps(current, indent=2)}\n\n"
            f"Recent history (up to 10):\n{json.dumps(hist_summary, indent=2)}"
        )
