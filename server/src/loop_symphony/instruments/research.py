"""Research instrument - iterative scientific method loop."""

import logging
import time
from datetime import UTC, datetime

from loop_symphony.config import get_settings
from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext
from loop_symphony.termination.evaluator import TerminationEvaluator
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.tools.tavily import TavilyClient

logger = logging.getLogger(__name__)


class ResearchInstrument(BaseInstrument):
    """Research instrument for iterative web research.

    Follows the scientific method:
    1. Problem: Define what we're researching
    2. Hypothesis: Generate search queries
    3. Test: Execute web searches
    4. Analysis: Synthesize findings with Claude
    5. Reflection: Check termination criteria

    Max 5 iterations (default), terminates on confidence >0.8, saturation, or bounds.
    """

    name = "research"
    required_capabilities = frozenset({"reasoning", "web_search"})
    optional_capabilities = frozenset({"synthesis", "analysis"})

    def __init__(
        self,
        *,
        claude: ClaudeClient | None = None,
        tavily: TavilyClient | None = None,
    ) -> None:
        settings = get_settings()
        self.max_iterations = settings.research_max_iterations
        self.claude = claude if claude is not None else ClaudeClient()
        self.tavily = tavily if tavily is not None else TavilyClient()
        self.termination = TerminationEvaluator()

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        """Execute iterative research loop.

        Args:
            query: The research query
            context: Optional task context

        Returns:
            InstrumentResult with accumulated findings
        """
        logger.info(f"Research instrument executing: {query[:50]}...")

        # State tracking
        findings: list[Finding] = []
        sources_consulted: list[str] = []
        confidence_history: list[float] = []
        iteration = 0
        outcome = Outcome.BOUNDED
        termination_reason = ""

        # Phase 1: Problem Definition
        problem = await self._define_problem(query, context)
        logger.debug(f"Problem defined: {problem[:100]}...")

        checkpoint_fn = context.checkpoint_fn if context else None

        while iteration < self.max_iterations:
            iteration += 1
            iteration_start = time.time()
            logger.info(f"Research iteration {iteration}/{self.max_iterations}")
            previous_finding_count = len(findings)

            # Phase 2: Hypothesis - generate search queries
            search_queries = await self._generate_hypotheses(
                problem, findings, iteration
            )
            logger.debug(f"Generated {len(search_queries)} search queries")

            # Phase 3: Test - execute searches
            new_findings, new_sources = await self._test_hypotheses(search_queries)
            findings.extend(new_findings)
            sources_consulted.extend(new_sources)
            logger.debug(f"Found {len(new_findings)} new findings")

            # Phase 4: Analysis - calculate confidence
            confidence = self.termination.calculate_confidence(
                findings,
                len(set(sources_consulted)),
                has_answer=any(f.confidence > 0.8 for f in new_findings),
            )
            confidence_history.append(confidence)
            logger.debug(f"Current confidence: {confidence:.2f}")

            # Phase 5: Reflection - check termination
            result = self.termination.evaluate(
                findings,
                iteration,
                self.max_iterations,
                confidence_history,
                previous_finding_count,
            )

            # Emit checkpoint for this iteration
            if checkpoint_fn:
                iteration_ms = int((time.time() - iteration_start) * 1000)
                try:
                    await checkpoint_fn(
                        iteration,
                        "iteration",
                        {"search_queries": search_queries},
                        {
                            "new_findings": len(new_findings),
                            "total_findings": len(findings),
                            "confidence": confidence,
                            "should_terminate": result.should_terminate,
                        },
                        iteration_ms,
                    )
                except Exception as e:
                    logger.warning(f"Checkpoint emission failed: {e}")

            if result.should_terminate:
                outcome = result.outcome
                termination_reason = result.reason
                logger.info(f"Terminating: {result.reason}")
                break

        # Synthesize final summary and detect contradictions
        summary, has_contradictions, hint = await self._synthesize_findings(
            query, findings
        )

        confidence = confidence_history[-1] if confidence_history else 0.0
        discrepancy = None
        followups: list[str] = []

        if has_contradictions and hint:
            analysis = await self._analyze_discrepancy(query, findings, hint)
            if analysis:
                discrepancy_desc, severity, refinements = analysis
                discrepancy = discrepancy_desc
                outcome = self._determine_outcome_with_discrepancy(
                    outcome, confidence, severity
                )
                if outcome == Outcome.INCONCLUSIVE and refinements:
                    followups = refinements

        if not followups:
            followups = await self._suggest_followups(query, findings, outcome)

        return InstrumentResult(
            outcome=outcome,
            findings=findings,
            summary=summary,
            confidence=confidence,
            iterations=iteration,
            sources_consulted=list(set(sources_consulted)),
            discrepancy=discrepancy,
            suggested_followups=followups,
        )

    async def _define_problem(
        self, query: str, context: TaskContext | None
    ) -> str:
        """Phase 1: Define the research problem clearly."""
        system = (
            "You are a research planner. Your job is to clearly define the research "
            "problem based on the user's query. Be specific about what information "
            "is needed and what would constitute a complete answer."
        )

        context_str = ""
        if context:
            if context.conversation_summary:
                context_str += f"\nConversation context: {context.conversation_summary}"
            if context.location:
                context_str += f"\nUser location: {context.location}"

        prompt = f"""Define the research problem for this query:

Query: {query}
{context_str}

Provide a clear, focused problem statement that will guide the research."""

        return await self.claude.complete(prompt, system=system)

    async def _generate_hypotheses(
        self,
        problem: str,
        existing_findings: list[Finding],
        iteration: int,
    ) -> list[str]:
        """Phase 2: Generate search queries (hypotheses)."""
        system = (
            "You are a search query generator. Generate 2-3 specific, targeted search "
            "queries that will help find information to answer the research problem. "
            "Each query should be different and cover different aspects."
        )

        existing = ""
        if existing_findings:
            existing = "\n\nExisting findings (don't search for these again):\n"
            existing += "\n".join(f"- {f.content[:100]}..." for f in existing_findings[-5:])

        prompt = f"""Research Problem: {problem}

Iteration: {iteration}
{existing}

Generate 2-3 search queries. Return ONLY the queries, one per line, no numbering or explanation."""

        response = await self.claude.complete(prompt, system=system)

        # Parse queries from response
        queries = [q.strip() for q in response.strip().split("\n") if q.strip()]
        return queries[:3]  # Limit to 3 queries

    async def _test_hypotheses(
        self, queries: list[str]
    ) -> tuple[list[Finding], list[str]]:
        """Phase 3: Execute searches and collect findings."""
        findings: list[Finding] = []
        sources: list[str] = []

        try:
            search_results = await self.tavily.search_multiple(
                queries, max_results_per_query=3
            )

            for search_response in search_results:
                # Add Tavily's AI answer if available
                if search_response.answer:
                    findings.append(
                        Finding(
                            content=search_response.answer,
                            source="tavily_answer",
                            confidence=0.85,
                            timestamp=datetime.now(UTC),
                        )
                    )

                # Add individual search results
                for result in search_response.results:
                    sources.append(result.url)
                    findings.append(
                        Finding(
                            content=f"{result.title}: {result.content}",
                            source=result.url,
                            confidence=result.score,
                            timestamp=datetime.now(UTC),
                        )
                    )

        except Exception as e:
            logger.error(f"Search failed: {e}")
            # Continue with empty findings rather than failing

        return findings, sources

    async def _synthesize_findings(
        self, query: str, findings: list[Finding]
    ) -> tuple[str, bool, str | None]:
        """Phase 4: Synthesize all findings and detect contradictions.

        Returns:
            Tuple of (summary, has_contradictions, contradiction_hint)
        """
        if not findings:
            return "No findings were discovered during research.", False, None

        findings_text = [f.content for f in findings]
        result = await self.claude.synthesize_with_analysis(findings_text, query)
        return (
            result["summary"],
            result["has_contradictions"],
            result["contradiction_hint"],
        )

    async def _analyze_discrepancy(
        self,
        query: str,
        findings: list[Finding],
        hint: str,
    ) -> tuple[str, str, list[str]] | None:
        """Analyze a detected contradiction in depth.

        Returns:
            Tuple of (description, severity, refinements) or None on failure
        """
        try:
            findings_text = [f.content for f in findings]
            result = await self.claude.analyze_discrepancy(
                findings_text, query, hint
            )
            return (
                result["description"],
                result["severity"],
                result.get("suggested_refinements", []),
            )
        except Exception as e:
            logger.warning(f"Discrepancy analysis failed: {e}")
            return None

    @staticmethod
    def _determine_outcome_with_discrepancy(
        original_outcome: Outcome,
        confidence: float,
        severity: str,
    ) -> Outcome:
        """Determine final outcome considering discrepancy severity.

        Args:
            original_outcome: The outcome from the termination evaluator
            confidence: Current confidence score
            severity: One of "minor", "moderate", "significant"

        Returns:
            Adjusted Outcome
        """
        if severity == "significant":
            return Outcome.INCONCLUSIVE

        if severity == "moderate":
            if original_outcome == Outcome.COMPLETE and confidence >= 0.9:
                return original_outcome
            return Outcome.INCONCLUSIVE

        # minor — keep original outcome
        return original_outcome

    async def _suggest_followups(
        self,
        query: str,
        findings: list[Finding],
        outcome: Outcome,
    ) -> list[str]:
        """Generate suggested follow-up questions."""
        if outcome == Outcome.COMPLETE and len(findings) > 3:
            # Enough info, suggest deeper dives
            system = (
                "Based on the research completed, suggest 2-3 follow-up questions "
                "the user might want to explore. Be specific and actionable."
            )
        else:
            # Incomplete, suggest clarifying questions
            system = (
                "The research was incomplete. Suggest 2-3 follow-up questions "
                "that could help get better results. Consider what information "
                "might be missing or unclear."
            )

        findings_summary = "\n".join(f.content[:100] for f in findings[:5])

        prompt = f"""Original query: {query}
Research outcome: {outcome.value}

Key findings:
{findings_summary}

Suggest 2-3 follow-up questions. Return ONLY the questions, one per line."""

        try:
            response = await self.claude.complete(prompt, system=system)
            questions = [q.strip() for q in response.strip().split("\n") if q.strip()]
            return questions[:3]
        except Exception:
            return []
