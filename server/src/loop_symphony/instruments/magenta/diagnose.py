"""Diagnose instrument — stage 2 of the Magenta Loop.

Runs three diagnostic tests on ingested analytics data:
1. Seed audience test (subscriber feed impressions vs subscriber count)
2. Stranger test (browse/suggested traffic vs subscriber feed)
3. 70% viewed threshold (avg view duration vs total length)
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


class DiagnoseInstrument(BaseInstrument):
    """Run diagnostic tests on ingested analytics and produce typed diagnoses."""

    name = "magenta_diagnose"
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
        logger.info("Magenta diagnose starting")

        # Read ingest output
        ingest_output = self._get_previous_output(context)
        if ingest_output is None:
            return InstrumentResult(
                outcome=Outcome.INCONCLUSIVE,
                findings=[],
                summary="No ingest data available for diagnosis.",
                confidence=0.0,
                iterations=1,
                sources_consulted=[],
            )

        # Try to get benchmarks
        benchmarks: dict | None = None
        try:
            benchmarks = await self.db.get_benchmarks(
                platform="youtube",
                category=ingest_output.get("category", "general"),
                subscriber_tier=self._determine_tier(
                    ingest_output.get("subscriber_count", 0)
                ),
            )
        except Exception as exc:
            logger.warning(f"Benchmark fetch failed (non-fatal): {exc}")

        # Run diagnoses via Claude
        prompt = self._build_diagnosis_prompt(ingest_output, benchmarks)
        system = (
            "You are a YouTube content strategist. Run three diagnostic tests:\n"
            "1. SEED AUDIENCE TEST: Compare subscriber-feed impressions to subscriber count. "
            "If < 30% of subscribers see it in feed, flag SUBSCRIBER_ONLY or WEAK_HOOK.\n"
            "2. STRANGER TEST: Check browse/suggested traffic ratio. "
            "If < 20% of views from non-subscribers, flag AUDIENCE_MISMATCH.\n"
            "3. 70% VIEWED THRESHOLD: If avg view percentage < 70% of total duration, "
            "check where drop-off occurs. Flag RETENTION_DROP or THUMBNAIL_UNDERPERFORMANCE.\n\n"
            "For each test, evaluate the data and determine if an issue exists.\n"
            "If content outperforms benchmarks, include a STRONG_PERFORMANCE diagnosis.\n\n"
            "Output valid JSON: a list of diagnosis objects, each with keys:\n"
            "diagnosis_type (one of: WEAK_HOOK, RETENTION_DROP, THUMBNAIL_UNDERPERFORMANCE, "
            "POSTING_TIME_WRONG, SUBSCRIBER_ONLY, AUDIENCE_MISMATCH, STRONG_PERFORMANCE),\n"
            "severity (low/medium/high), title, description, evidence, "
            "metric_value (float or null), benchmark_value (float or null)."
        )

        response = await self.claude.complete(prompt, system=system)

        finding = Finding(
            content=response,
            source="magenta_diagnose",
            confidence=0.85,
        )

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response,
            confidence=0.85,
            iterations=1,
            sources_consulted=["content_performance_db", "content_benchmarks_db", "claude"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_previous_output(context: TaskContext | None) -> dict | None:
        if context is None or not context.input_results:
            return None
        prev = context.input_results[0]
        if isinstance(prev, dict):
            return prev
        return None

    @staticmethod
    def _determine_tier(subscriber_count: int) -> str:
        if subscriber_count < 1_000:
            return "0-1k"
        elif subscriber_count < 10_000:
            return "1k-10k"
        elif subscriber_count < 100_000:
            return "10k-100k"
        elif subscriber_count < 1_000_000:
            return "100k-1m"
        return "1m+"

    @staticmethod
    def _build_diagnosis_prompt(
        ingest_output: dict,
        benchmarks: dict | None,
    ) -> str:
        parts = [f"Ingested analytics summary:\n{json.dumps(ingest_output, indent=2, default=str)}"]
        if benchmarks:
            parts.append(f"\nCategory benchmarks:\n{json.dumps(benchmarks, indent=2, default=str)}")
        else:
            parts.append("\nNo category benchmarks available — use general YouTube averages.")
        return "\n".join(parts)
