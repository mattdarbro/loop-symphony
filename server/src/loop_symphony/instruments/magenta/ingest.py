"""Ingest instrument — stage 1 of the Magenta Loop.

Extracts raw analytics from context, validates, stores in DB,
and fetches historical data for comparison.
"""

import json
import logging

from loop_symphony.db.client import DatabaseClient
from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.magenta import ContentMetrics
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext
from loop_symphony.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {"content_id", "creator_id", "views"}


class IngestInstrument(BaseInstrument):
    """Ingest raw analytics data, store, and compare to history.

    Single-cycle: validates input, persists to content_performance,
    fetches last 20 entries, and uses Claude to summarise trends.
    """

    name = "magenta_ingest"
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
        logger.info("Magenta ingest starting")

        # Extract analytics payload from input_results
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

        # Validate required fields
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

        # Parse into model for validation
        metrics = ContentMetrics(**raw)

        # Store in DB
        app_id = context.app_id if context else None
        db_record = {
            "app_id": app_id,
            "content_id": metrics.content_id,
            "creator_id": metrics.creator_id,
            "platform": metrics.platform,
            "title": metrics.title,
            "published_at": metrics.published_at.isoformat() if metrics.published_at else None,
            "views": metrics.views,
            "likes": metrics.likes,
            "comments": metrics.comments,
            "shares": metrics.shares,
            "subscribers_gained": metrics.subscribers_gained,
            "subscribers_lost": metrics.subscribers_lost,
            "avg_view_duration_seconds": metrics.avg_view_duration_seconds,
            "avg_view_percentage": metrics.avg_view_percentage,
            "retention_curve": json.dumps(metrics.retention_curve),
            "total_duration_seconds": metrics.total_duration_seconds,
            "traffic_sources": json.dumps(metrics.traffic_sources),
            "demographics": json.dumps(metrics.demographics),
            "subscriber_count": metrics.subscriber_count,
            "category": metrics.category,
            "impressions": metrics.impressions,
            "impression_click_through_rate": metrics.impression_click_through_rate,
        }

        try:
            await self.db.upsert_content_performance(db_record)
        except Exception as exc:
            logger.warning(f"DB upsert failed (non-fatal): {exc}")

        # Fetch history
        history: list[dict] = []
        try:
            history = await self.db.list_creator_content(
                metrics.creator_id, limit=20
            )
        except Exception as exc:
            logger.warning(f"History fetch failed (non-fatal): {exc}")

        # Summarise via Claude
        prompt = self._build_summary_prompt(metrics, history)
        system = (
            "You are a YouTube analytics expert. Summarise the current "
            "content's performance compared to the creator's recent history. "
            "Be specific with numbers. Output JSON with keys: "
            "summary, trends (list[str]), notable_changes (list[str])."
        )

        response = await self.claude.complete(prompt, system=system)

        finding = Finding(
            content=response,
            source="magenta_ingest",
            confidence=0.9,
        )

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response,
            confidence=0.9,
            iterations=1,
            sources_consulted=["content_performance_db", "claude"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_analytics(context: TaskContext | None) -> dict | None:
        """Pull the raw analytics dict from context.input_results[0]."""
        if context is None:
            return None
        if not context.input_results:
            return None
        first = context.input_results[0]
        if isinstance(first, dict):
            # Could be wrapped as {"analytics": {...}} or flat
            return first.get("analytics", first)
        return None

    @staticmethod
    def _build_summary_prompt(
        metrics: ContentMetrics,
        history: list[dict],
    ) -> str:
        current = {
            "content_id": metrics.content_id,
            "title": metrics.title,
            "views": metrics.views,
            "likes": metrics.likes,
            "comments": metrics.comments,
            "avg_view_percentage": metrics.avg_view_percentage,
            "impressions": metrics.impressions,
            "ctr": metrics.impression_click_through_rate,
            "subscriber_count": metrics.subscriber_count,
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
