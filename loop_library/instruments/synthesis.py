"""Synthesis instrument - merges multiple InstrumentResult objects."""

import logging
from datetime import UTC, datetime

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)

_RESYNTHESIS_THRESHOLD = 0.6


class SynthesisInstrument(BaseInstrument):
    """Synthesis instrument for merging multiple instrument results."""

    name = "synthesis"
    max_iterations = 2
    required_capabilities = frozenset({"reasoning", "synthesis"})

    def __init__(self, *, claude: ClaudeClient | None = None) -> None:
        self.claude = claude if claude is not None else ClaudeClient()

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        logger.info(f"Synthesis instrument executing: {query[:50]}...")

        input_results = self._extract_input_results(context)
        if not input_results:
            logger.warning("Synthesis called with no input results")
            return self._empty_result(query)

        all_findings, sources = self._collect_findings(input_results)
        if not all_findings:
            logger.warning("No findings in input results")
            return self._empty_result(query)

        iteration = 1
        summary, has_contradictions, hint = await self._synthesize(query, all_findings)
        confidence = self._calculate_merged_confidence(input_results, all_findings)

        discrepancy = None
        outcome = Outcome.COMPLETE
        followups: list[str] = []

        if has_contradictions and hint:
            discrepancy, outcome, followups = await self._handle_contradictions(
                query, all_findings, hint, confidence
            )

        if confidence < _RESYNTHESIS_THRESHOLD and iteration < self.max_iterations:
            iteration = 2
            summary, has_contradictions, hint = await self._resynthesize(
                query, all_findings, summary, confidence
            )
            confidence = min(1.0, confidence + 0.05)
            if has_contradictions and hint and discrepancy is None:
                discrepancy, outcome, followups = await self._handle_contradictions(
                    query, all_findings, hint, confidence
                )

        return InstrumentResult(
            outcome=outcome,
            findings=all_findings,
            summary=summary,
            confidence=confidence,
            iterations=iteration,
            sources_consulted=sources,
            discrepancy=discrepancy,
            suggested_followups=followups,
        )

    @staticmethod
    def _extract_input_results(context: TaskContext | None) -> list[dict]:
        if context is None:
            return []
        return context.input_results or []

    @staticmethod
    def _collect_findings(input_results: list[dict]) -> tuple[list[Finding], list[str]]:
        findings: list[Finding] = []
        sources: set[str] = set()
        for result in input_results:
            for src in result.get("sources_consulted", []):
                sources.add(src)
            for f_dict in result.get("findings", []):
                findings.append(
                    Finding(
                        content=f_dict["content"],
                        source=f_dict.get("source"),
                        confidence=f_dict.get("confidence", 0.5),
                    )
                )
        return findings, sorted(sources)

    async def _synthesize(
        self, query: str, findings: list[Finding],
    ) -> tuple[str, bool, str | None]:
        findings_text = self._weighted_findings_text(findings)
        result = await self.claude.synthesize_with_analysis(findings_text, query)
        return (result["summary"], result["has_contradictions"], result["contradiction_hint"])

    async def _resynthesize(
        self, query: str, findings: list[Finding], previous_summary: str, previous_confidence: float,
    ) -> tuple[str, bool, str | None]:
        findings_text = self._weighted_findings_text(findings)
        refinement_context = (
            f"[Previous synthesis attempt (confidence: {previous_confidence:.2f})]: "
            f"{previous_summary}\n\n"
            f"Please re-examine the findings more carefully and produce "
            f"a more precise synthesis."
        )
        enriched_findings = [refinement_context] + findings_text
        result = await self.claude.synthesize_with_analysis(enriched_findings, query)
        return (result["summary"], result["has_contradictions"], result["contradiction_hint"])

    async def _handle_contradictions(
        self, query: str, findings: list[Finding], hint: str, confidence: float,
    ) -> tuple[str | None, Outcome, list[str]]:
        try:
            findings_text = [f.content for f in findings]
            analysis = await self.claude.analyze_discrepancy(findings_text, query, hint)
            description = analysis["description"]
            severity = analysis.get("severity", "moderate")
            refinements = analysis.get("suggested_refinements", [])
            outcome = self._determine_outcome(confidence, severity)
            followups = refinements if outcome == Outcome.INCONCLUSIVE else []
            return description, outcome, followups
        except Exception as e:
            logger.warning(f"Contradiction analysis failed: {e}")
            return None, Outcome.COMPLETE, []

    @staticmethod
    def _determine_outcome(confidence: float, severity: str) -> Outcome:
        if severity == "significant":
            return Outcome.INCONCLUSIVE
        if severity == "moderate" and confidence < 0.9:
            return Outcome.INCONCLUSIVE
        return Outcome.COMPLETE

    @staticmethod
    def _calculate_merged_confidence(input_results: list[dict], findings: list[Finding]) -> float:
        if not input_results:
            return 0.0
        total_weight = 0.0
        weighted_sum = 0.0
        for result in input_results:
            result_confidence = result.get("confidence", 0.5)
            finding_count = len(result.get("findings", []))
            weight = max(1, finding_count)
            weighted_sum += result_confidence * weight
            total_weight += weight
        if total_weight == 0:
            return 0.0
        base_confidence = weighted_sum / total_weight
        confidences = [r.get("confidence", 0.5) for r in input_results]
        if len(confidences) >= 2 and all(c >= 0.7 for c in confidences):
            agreement_bonus = 0.05
        else:
            agreement_bonus = 0.0
        return min(1.0, base_confidence + agreement_bonus)

    @staticmethod
    def _weighted_findings_text(findings: list[Finding]) -> list[str]:
        result = []
        for f in findings:
            if f.confidence >= 0.8:
                prefix = "[HIGH CONFIDENCE] "
            elif f.confidence >= 0.5:
                prefix = ""
            else:
                prefix = "[LOW CONFIDENCE] "
            result.append(f"{prefix}{f.content}")
        return result

    def _empty_result(self, query: str) -> InstrumentResult:
        return InstrumentResult(
            outcome=Outcome.BOUNDED,
            findings=[],
            summary=f"No input results available to synthesize for query: {query}",
            confidence=0.0,
            iterations=0,
            sources_consulted=[],
            discrepancy=None,
            suggested_followups=["Try running research instruments first to gather findings"],
        )
