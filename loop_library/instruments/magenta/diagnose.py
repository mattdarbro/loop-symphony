"""Diagnose instrument — stage 2 of the Magenta Loop."""

import json
import logging
from typing import Any

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.tools.claude import ClaudeClient

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
        db: Any = None,
    ) -> None:
        self.claude = claude if claude is not None else ClaudeClient()
        self.db = db

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        logger.info("Magenta diagnose starting")

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

        benchmarks: dict | None = None
        if self.db is not None:
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

        prompt = self._build_diagnosis_prompt(ingest_output, benchmarks)
        system = (
            "You are a YouTube content strategist. Run three diagnostic tests:\n"
            "1. SEED AUDIENCE TEST: Compare subscriber-feed impressions to subscriber count. "
            "If < 30% of subscribers see it in feed, flag SUBSCRIBER_ONLY or WEAK_HOOK.\n"
            "2. STRANGER TEST: Check browse/suggested traffic ratio. "
            "If < 20% of views from non-subscribers, flag AUDIENCE_MISMATCH.\n"
            "3. 70% VIEWED THRESHOLD: If avg view percentage < 70% of total duration, "
            "check where drop-off occurs. Flag RETENTION_DROP or THUMBNAIL_UNDERPERFORMANCE.\n\n"
            "Output valid JSON: a list of diagnosis objects."
        )

        response = await self.claude.complete(prompt, system=system)

        finding = Finding(content=response, source="magenta_diagnose", confidence=0.85)

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response,
            confidence=0.85,
            iterations=1,
            sources_consulted=["content_performance_db", "content_benchmarks_db", "claude"],
        )

    @staticmethod
    def _get_previous_output(context: TaskContext | None) -> dict | None:
        if context is None or not context.input_results:
            return None
        prev = context.input_results[0]
        return prev if isinstance(prev, dict) else None

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
    def _build_diagnosis_prompt(ingest_output: dict, benchmarks: dict | None) -> str:
        parts = [f"Ingested analytics summary:\n{json.dumps(ingest_output, indent=2, default=str)}"]
        if benchmarks:
            parts.append(f"\nCategory benchmarks:\n{json.dumps(benchmarks, indent=2, default=str)}")
        else:
            parts.append("\nNo category benchmarks available — use general YouTube averages.")
        return "\n".join(parts)
