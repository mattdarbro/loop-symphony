"""Report instrument — stage 5 of the Magenta Loop.

Generates a narrative-style briefing from all prior pipeline outputs,
stores the report, and prepares a notification payload.
"""

import json
import logging
from uuid import uuid4

from loop_symphony.db.client import DatabaseClient
from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext
from loop_symphony.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)


class ReportInstrument(BaseInstrument):
    """Generate a narrative report from the full pipeline output."""

    name = "magenta_report"
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
        logger.info("Magenta report starting")

        # Read all prior stage outputs
        prior_output = self._get_previous_output(context)
        if prior_output is None:
            return InstrumentResult(
                outcome=Outcome.INCONCLUSIVE,
                findings=[],
                summary="No pipeline data available for report generation.",
                confidence=0.0,
                iterations=1,
                sources_consulted=[],
            )

        # Determine report type
        report_type = self._determine_report_type(prior_output)

        # Generate narrative via Claude
        prompt = self._build_report_prompt(prior_output, report_type)
        system = (
            "You are writing a content performance briefing for a YouTube creator. "
            "Write it like a letter from a trusted business partner — warm, direct, "
            "specific, and actionable. Use the creator's actual numbers.\n\n"
            "Structure:\n"
            "1. Opening — how the content is doing overall (1-2 sentences)\n"
            "2. Key findings — what the diagnostics revealed\n"
            "3. Recommendations — specific next steps from the prescriptions\n"
            "4. Learning — what we learned from tracking past advice\n"
            "5. Closing — encouraging next step\n\n"
            "Output valid JSON with keys: title, narrative, diagnoses_count (int), "
            "prescriptions_count (int), tracking_summary (string or null), "
            "notification_title (short string for push notification), "
            "notification_body (1-sentence summary for push notification)."
        )

        response = await self.claude.complete(prompt, system=system)

        # Store report in DB
        app_id = context.app_id if context else None
        creator_id = self._extract_creator_id(context)
        try:
            parsed = json.loads(response) if isinstance(response, str) else response
            if isinstance(parsed, dict):
                report_record = {
                    "id": str(uuid4()),
                    "app_id": app_id,
                    "creator_id": creator_id or "unknown",
                    "report_type": report_type,
                    "title": parsed.get("title", "Content Performance Report"),
                    "narrative": parsed.get("narrative", response),
                    "diagnoses_count": parsed.get("diagnoses_count", 0),
                    "prescriptions_count": parsed.get("prescriptions_count", 0),
                    "tracking_summary": parsed.get("tracking_summary"),
                    "notification_payload": json.dumps({
                        "title": parsed.get("notification_title", "New Report"),
                        "body": parsed.get("notification_body", "Your content report is ready."),
                    }),
                }
                await self.db.create_content_report(report_record)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(f"Report storage failed (non-fatal): {exc}")

        finding = Finding(
            content=response,
            source="magenta_report",
            confidence=0.85,
        )

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response,
            confidence=0.85,
            iterations=1,
            sources_consulted=["pipeline_outputs", "claude"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
    def _determine_report_type(prior_output: dict) -> str:
        """Determine report type based on pipeline data."""
        summary = str(prior_output.get("summary", "")).lower()
        findings = prior_output.get("findings", [])

        # Check for urgent indicators
        for finding in findings:
            content = str(finding.get("content", "")).lower()
            if any(word in content for word in ["urgent", "critical", "severe", "high severity"]):
                return "urgent"

        # Check for weekly cadence
        if "weekly" in summary:
            return "weekly"

        return "standard"

    @staticmethod
    def _build_report_prompt(prior_output: dict, report_type: str) -> str:
        return (
            f"Report type: {report_type}\n\n"
            f"Pipeline output from all stages:\n"
            f"{json.dumps(prior_output, indent=2, default=str)}"
        )
