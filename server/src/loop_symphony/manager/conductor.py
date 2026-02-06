"""Conductor - task analysis and instrument routing."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from loop_symphony.exceptions import DepthExceededError
from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.instruments.note import NoteInstrument
from loop_symphony.instruments.research import ResearchInstrument
from loop_symphony.instruments.synthesis import SynthesisInstrument
from loop_symphony.instruments.vision import VisionInstrument
from loop_symphony.models.arrangement import ArrangementProposal, ArrangementValidation
from loop_symphony.models.finding import ExecutionMetadata
from loop_symphony.models.loop_proposal import (
    LoopExecutionPlan,
    LoopProposal,
    LoopProposalValidation,
)
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskContext, TaskRequest, TaskResponse
from loop_symphony.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from loop_symphony.manager.arrangement_planner import ArrangementPlanner
    from loop_symphony.manager.arrangement_tracker import ArrangementTracker
    from loop_symphony.manager.loop_executor import LoopExecutor
    from loop_symphony.manager.loop_proposer import LoopProposer

logger = logging.getLogger(__name__)

# Keywords that suggest research is needed
RESEARCH_KEYWORDS = [
    "research",
    "find",
    "search",
    "look up",
    "investigate",
    "explore",
    "discover",
    "latest",
    "recent",
    "current",
    "news",
    "developments",
    "trends",
    "compare",
    "comparison",
    "review",
    "analysis",
    "what are the best",
    "how do I",
    "guide",
    "tutorial",
]

# Patterns that suggest complex queries needing research
COMPLEX_PATTERNS = [
    r"\band\b.*\band\b",  # Multiple "and" conjunctions
    r"\bvs\.?\b",  # Comparisons
    r"\bversus\b",
    r"\bdifference between\b",
    r"\bpros and cons\b",
    r"\badvantages\b.*\bdisadvantages\b",
]

# Map instrument names to process visibility types
_INSTRUMENT_PROCESS_TYPE: dict[str, ProcessType] = {
    "note": ProcessType.AUTONOMIC,
    "research": ProcessType.SEMI_AUTONOMIC,
    "synthesis": ProcessType.SEMI_AUTONOMIC,
    "vision": ProcessType.SEMI_AUTONOMIC,
}

# Indicators that an attachment is an image
_IMAGE_INDICATORS = ("data:image/", ".jpg", ".jpeg", ".png", ".gif", ".webp")


def _has_image_attachments(context: TaskContext | None) -> bool:
    """Check if context contains image-like attachments."""
    if not context or not context.attachments:
        return False
    for att in context.attachments:
        att_lower = att.lower().split("?")[0]
        if any(indicator in att_lower for indicator in _IMAGE_INDICATORS):
            return True
        if att.startswith("https://"):
            return True
    return False


class Conductor:
    """The conductor orchestrates task execution.

    Analyzes incoming tasks and routes them to the appropriate instrument.
    Supports novel arrangement generation (Phase 3A) and loop proposals (Phase 3B).
    """

    def __init__(self, *, registry: ToolRegistry | None = None) -> None:
        self.registry = registry
        self._planner: ArrangementPlanner | None = None
        self._loop_proposer: LoopProposer | None = None
        self._loop_executor: LoopExecutor | None = None
        self._tracker: ArrangementTracker | None = None
        if registry is not None:
            self.instruments: dict[str, BaseInstrument] = {
                "note": self._build_instrument("note"),
                "research": self._build_instrument("research"),
                "synthesis": self._build_instrument("synthesis"),
                "vision": self._build_instrument("vision"),
            }
        else:
            self.instruments: dict[str, BaseInstrument] = {
                "note": NoteInstrument(),
                "research": ResearchInstrument(),
                "synthesis": SynthesisInstrument(),
                "vision": VisionInstrument(),
            }

    def _get_planner(self) -> ArrangementPlanner:
        """Lazy initialization of arrangement planner."""
        if self._planner is None:
            from loop_symphony.manager.arrangement_planner import ArrangementPlanner
            from loop_symphony.tools.claude import ClaudeClient

            # Get Claude from registry or create new instance
            if self.registry is not None:
                claude = self.registry.get_by_capability("reasoning")
            else:
                claude = ClaudeClient()

            self._planner = ArrangementPlanner(claude=claude, registry=self.registry)
        return self._planner

    def _get_loop_proposer(self) -> LoopProposer:
        """Lazy initialization of loop proposer."""
        if self._loop_proposer is None:
            from loop_symphony.manager.loop_proposer import LoopProposer
            from loop_symphony.tools.claude import ClaudeClient

            if self.registry is not None:
                claude = self.registry.get_by_capability("reasoning")
            else:
                claude = ClaudeClient()

            self._loop_proposer = LoopProposer(claude=claude)
        return self._loop_proposer

    def _get_loop_executor(self) -> LoopExecutor:
        """Lazy initialization of loop executor."""
        if self._loop_executor is None:
            from loop_symphony.manager.loop_executor import LoopExecutor
            from loop_symphony.tools.claude import ClaudeClient

            if self.registry is not None:
                claude = self.registry.get_by_capability("reasoning")
            else:
                claude = ClaudeClient()

            self._loop_executor = LoopExecutor(claude=claude, conductor=self)
        return self._loop_executor

    def _get_tracker(self) -> ArrangementTracker:
        """Lazy initialization of arrangement tracker."""
        if self._tracker is None:
            from loop_symphony.manager.arrangement_tracker import ArrangementTracker
            self._tracker = ArrangementTracker()
        return self._tracker

    @property
    def tracker(self) -> ArrangementTracker:
        """Public access to the arrangement tracker."""
        return self._get_tracker()

    def _build_instrument(self, name: str) -> BaseInstrument:
        """Build an instrument with tools resolved from the registry."""
        if name == "note":
            tools = self.registry.resolve(NoteInstrument.required_capabilities)
            return NoteInstrument(claude=tools["reasoning"])
        elif name == "research":
            tools = self.registry.resolve(
                ResearchInstrument.required_capabilities,
                ResearchInstrument.optional_capabilities,
            )
            return ResearchInstrument(
                claude=tools["reasoning"],
                tavily=tools["web_search"],
            )
        elif name == "synthesis":
            tools = self.registry.resolve(SynthesisInstrument.required_capabilities)
            return SynthesisInstrument(claude=tools["reasoning"])
        elif name == "vision":
            tools = self.registry.resolve(VisionInstrument.required_capabilities)
            return VisionInstrument(claude=tools["reasoning"])
        raise ValueError(f"Unknown instrument: {name}")

    async def analyze_and_route(self, request: TaskRequest) -> str:
        """Analyze task and determine which instrument to use.

        Phase 1 logic:
        - If query is simple question → "note"
        - If query mentions research/find/search → "research"
        - If query is complex/multi-part → "research"
        - Default → "note"

        Args:
            request: The incoming task request

        Returns:
            Name of the instrument to use
        """
        query = request.query.lower()

        # Check for vision: images in attachments (checked first)
        if _has_image_attachments(request.context):
            logger.debug("Routing to vision: image attachments detected")
            return "vision"

        # Check for research keywords
        for keyword in RESEARCH_KEYWORDS:
            if keyword in query:
                logger.debug(f"Routing to research: keyword '{keyword}' found")
                return "research"

        # Check for complex patterns
        for pattern in COMPLEX_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                logger.debug(f"Routing to research: complex pattern found")
                return "research"

        # Check query length and structure
        word_count = len(query.split())
        if word_count > 20:
            logger.debug(f"Routing to research: long query ({word_count} words)")
            return "research"

        # Check for question marks suggesting multi-part questions
        question_count = query.count("?")
        if question_count > 1:
            logger.debug(f"Routing to research: multiple questions ({question_count})")
            return "research"

        # Check thoroughness preference
        if request.preferences and request.preferences.thoroughness == "thorough":
            logger.debug("Routing to research: thorough preference")
            return "research"

        # Default to note for simple queries
        logger.debug("Routing to note: simple query")
        return "note"

    async def execute_composition(
        self,
        composition,
        request: TaskRequest,
    ) -> TaskResponse:
        """Execute a composition pipeline and wrap the result.

        Args:
            composition: Object with name and execute(query, context, conductor)
            request: The task request

        Returns:
            TaskResponse with results from the composition
        """
        start_time = time.time()

        logger.info(
            f"Executing composition '{composition.name}' for task {request.id}"
        )

        result: InstrumentResult = await composition.execute(
            request.query,
            request.context,
            self,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        return TaskResponse(
            request_id=request.id,
            outcome=result.outcome,
            findings=result.findings,
            summary=result.summary,
            confidence=result.confidence,
            metadata=ExecutionMetadata(
                instrument_used=composition.name,
                iterations=result.iterations,
                duration_ms=duration_ms,
                sources_consulted=result.sources_consulted,
                process_type=ProcessType.CONSCIOUS,
            ),
            discrepancy=result.discrepancy,
            suggested_followups=result.suggested_followups,
        )

    async def execute(self, request: TaskRequest) -> TaskResponse:
        """Execute a task request end-to-end.

        Args:
            request: The task request to execute

        Returns:
            TaskResponse with results
        """
        start_time = time.time()

        # Get or create context
        context = request.context or TaskContext()
        current_depth = context.depth

        # Determine max_depth: preference override > context > default
        max_depth = context.max_depth
        if request.preferences and request.preferences.max_spawn_depth is not None:
            max_depth = request.preferences.max_spawn_depth

        # Create spawn callback
        async def _spawn(
            sub_query: str,
            sub_context: TaskContext | None = None,
        ) -> InstrumentResult:
            """Spawn a sub-task at incremented depth.

            Args:
                sub_query: The query for the sub-task
                sub_context: Optional context to merge (e.g., input_results)

            Returns:
                InstrumentResult from the sub-task

            Raises:
                DepthExceededError: If spawning would exceed max_depth
            """
            new_depth = current_depth + 1
            if new_depth > max_depth:
                raise DepthExceededError(new_depth, max_depth)

            # Build sub-context from current, optionally merge sub_context fields
            base = context.model_copy(update={
                "depth": new_depth,
                "max_depth": max_depth,
                "spawn_fn": None,  # Will be re-injected by recursive call
            })

            if sub_context is not None:
                merge = {}
                if sub_context.input_results is not None:
                    merge["input_results"] = sub_context.input_results
                if sub_context.conversation_summary is not None:
                    merge["conversation_summary"] = sub_context.conversation_summary
                if sub_context.attachments:
                    merge["attachments"] = sub_context.attachments
                if merge:
                    base = base.model_copy(update=merge)

            sub_request = TaskRequest(
                query=sub_query,
                context=base,
                preferences=request.preferences,
            )

            # Recursive execution
            sub_response = await self.execute(sub_request)

            # Convert TaskResponse to InstrumentResult
            return InstrumentResult(
                outcome=sub_response.outcome,
                findings=sub_response.findings,
                summary=sub_response.summary,
                confidence=sub_response.confidence,
                iterations=sub_response.metadata.iterations,
                sources_consulted=sub_response.metadata.sources_consulted,
                discrepancy=sub_response.discrepancy,
                suggested_followups=sub_response.suggested_followups,
            )

        # Inject spawn_fn into context
        enriched_context = context.model_copy(update={
            "spawn_fn": _spawn,
            "depth": current_depth,
            "max_depth": max_depth,
        })
        request = request.model_copy(update={"context": enriched_context})

        # Route to appropriate instrument
        instrument_name = await self.analyze_and_route(request)
        instrument = self.instruments[instrument_name]

        logger.info(
            f"Executing task {request.id} with {instrument_name} instrument "
            f"(depth={current_depth}/{max_depth})"
        )

        # Execute the instrument
        result: InstrumentResult = await instrument.execute(
            request.query,
            request.context,
        )

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Build response
        return TaskResponse(
            request_id=request.id,
            outcome=result.outcome,
            findings=result.findings,
            summary=result.summary,
            confidence=result.confidence,
            metadata=ExecutionMetadata(
                instrument_used=instrument_name,
                iterations=result.iterations,
                duration_ms=duration_ms,
                sources_consulted=result.sources_consulted,
                process_type=_INSTRUMENT_PROCESS_TYPE.get(
                    instrument_name, ProcessType.SEMI_AUTONOMIC
                ),
            ),
            discrepancy=result.discrepancy,
            suggested_followups=result.suggested_followups,
        )

    # -------------------------------------------------------------------------
    # Novel Arrangement Methods (Phase 3A)
    # -------------------------------------------------------------------------

    async def plan_arrangement(self, query: str) -> ArrangementProposal:
        """Use Claude to plan a novel arrangement for a query.

        Args:
            query: The user's task query

        Returns:
            ArrangementProposal with recommended composition
        """
        planner = self._get_planner()
        return await planner.plan(query)

    def validate_arrangement(
        self, proposal: ArrangementProposal
    ) -> ArrangementValidation:
        """Validate an arrangement proposal.

        Args:
            proposal: The arrangement proposal to validate

        Returns:
            ArrangementValidation with errors and warnings
        """
        planner = self._get_planner()
        return planner.validate(proposal)

    async def execute_arrangement(
        self,
        proposal: ArrangementProposal,
        request: TaskRequest,
    ) -> TaskResponse:
        """Execute a validated arrangement proposal.

        Args:
            proposal: The validated arrangement proposal
            request: The task request

        Returns:
            TaskResponse with results

        Raises:
            ValueError: If proposal is invalid
        """
        from loop_symphony.manager.composition import (
            ParallelComposition,
            SequentialComposition,
        )

        validation = self.validate_arrangement(proposal)
        if not validation.valid:
            raise ValueError(f"Invalid arrangement: {validation.errors}")

        start_time = time.time()

        if proposal.type == "single":
            # Direct instrument execution
            instrument = self.instruments[proposal.instrument]
            result = await instrument.execute(request.query, request.context)
            instrument_name = proposal.instrument

        elif proposal.type == "sequential":
            # Build sequential composition from steps
            steps = [
                (step.instrument, step.config) for step in proposal.steps
            ]
            composition = SequentialComposition(steps)
            result = await composition.execute(
                request.query, request.context, self
            )
            instrument_name = composition.name

        elif proposal.type == "parallel":
            # Build parallel composition
            composition = ParallelComposition(
                branches=proposal.branches,
                merge_instrument=proposal.merge_instrument,
                timeout_seconds=proposal.timeout_seconds,
            )
            result = await composition.execute(
                request.query, request.context, self
            )
            instrument_name = composition.name

        else:
            raise ValueError(f"Unknown arrangement type: {proposal.type}")

        duration_ms = int((time.time() - start_time) * 1000)

        # Track execution for meta-learning
        self.tracker.record_execution(
            arrangement=proposal,
            task_id=request.id,
            outcome=result.outcome.value,
            confidence=result.confidence,
            duration_ms=duration_ms,
        )

        response = TaskResponse(
            request_id=request.id,
            outcome=result.outcome,
            findings=result.findings,
            summary=result.summary,
            confidence=result.confidence,
            metadata=ExecutionMetadata(
                instrument_used=f"novel:{instrument_name}",
                iterations=result.iterations,
                duration_ms=duration_ms,
                sources_consulted=result.sources_consulted,
                process_type=ProcessType.CONSCIOUS,
            ),
            discrepancy=result.discrepancy,
            suggested_followups=result.suggested_followups,
        )

        # Check if we should suggest saving this arrangement
        suggestion = self.tracker.get_suggestion(proposal)
        if suggestion:
            logger.info(
                f"Suggesting to save arrangement: {suggestion.suggested_name} "
                f"(success_rate={suggestion.success_rate:.2f})"
            )

        return response

    async def execute_novel(self, request: TaskRequest) -> TaskResponse:
        """Plan and execute a novel arrangement for a task.

        This is the high-level entry point for novel arrangement execution.
        It plans an arrangement, validates it, and executes it.

        Args:
            request: The task request

        Returns:
            TaskResponse with results
        """
        logger.info(f"Planning novel arrangement for task {request.id}")

        # Plan the arrangement
        proposal = await self.plan_arrangement(request.query)

        # Validate
        validation = self.validate_arrangement(proposal)
        if not validation.valid:
            logger.error(f"Invalid arrangement proposal: {validation.errors}")
            # Fall back to standard execution
            return await self.execute(request)

        if validation.warnings:
            for warning in validation.warnings:
                logger.warning(f"Arrangement warning: {warning}")

        logger.info(
            f"Executing novel arrangement: type={proposal.type}, "
            f"rationale={proposal.rationale[:50]}..."
        )

        # Execute the arrangement
        return await self.execute_arrangement(proposal, request)

    # -------------------------------------------------------------------------
    # Loop Proposal Methods (Phase 3B)
    # -------------------------------------------------------------------------

    async def propose_loop(self, query: str) -> LoopProposal:
        """Propose a new loop type for a query.

        Level 5 creativity: designs entirely new loop specifications
        when existing instruments don't fit.

        Args:
            query: The user's task query

        Returns:
            LoopProposal with custom loop specification
        """
        proposer = self._get_loop_proposer()
        return await proposer.propose(query)

    def validate_loop_proposal(
        self, proposal: LoopProposal
    ) -> LoopProposalValidation:
        """Validate a loop proposal.

        Checks scientific method coverage, valid instruments,
        termination criteria, and iteration bounds.

        Args:
            proposal: The loop proposal to validate

        Returns:
            LoopProposalValidation with errors and warnings
        """
        proposer = self._get_loop_proposer()
        return proposer.validate(proposal)

    def get_loop_execution_plan(
        self, proposal: LoopProposal
    ) -> LoopExecutionPlan:
        """Get an execution plan for a loop proposal.

        Used for trust_level=0 to show the user what will happen.

        Args:
            proposal: The loop proposal

        Returns:
            LoopExecutionPlan with estimates and validation
        """
        proposer = self._get_loop_proposer()
        validation = proposer.validate(proposal)
        estimates = proposer.get_execution_estimate(proposal)

        return LoopExecutionPlan(
            proposal=proposal,
            validation=validation,
            estimated_iterations=estimates["estimated_iterations"],
            estimated_duration_seconds=estimates["estimated_duration_seconds"],
            requires_approval=True,
        )

    async def execute_loop_proposal(
        self,
        proposal: LoopProposal,
        request: TaskRequest,
    ) -> TaskResponse:
        """Execute a validated loop proposal.

        Args:
            proposal: The validated loop proposal
            request: The task request

        Returns:
            TaskResponse with results

        Raises:
            ValueError: If proposal is invalid
        """
        validation = self.validate_loop_proposal(proposal)
        if not validation.valid:
            raise ValueError(f"Invalid loop proposal: {validation.errors}")

        start_time = time.time()

        logger.info(
            f"Executing loop proposal '{proposal.name}' for task {request.id}"
        )

        executor = self._get_loop_executor()
        result = await executor.execute(
            proposal,
            request.query,
            request.context,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # Track execution for meta-learning
        self.tracker.record_execution(
            arrangement=proposal,
            task_id=request.id,
            outcome=result.outcome.value,
            confidence=result.confidence,
            duration_ms=duration_ms,
        )

        response = TaskResponse(
            request_id=request.id,
            outcome=result.outcome,
            findings=result.findings,
            summary=result.summary,
            confidence=result.confidence,
            metadata=ExecutionMetadata(
                instrument_used=f"loop:{proposal.name}",
                iterations=result.iterations,
                duration_ms=duration_ms,
                sources_consulted=result.sources_consulted,
                process_type=ProcessType.CONSCIOUS,
            ),
            discrepancy=result.discrepancy,
            suggested_followups=result.suggested_followups,
        )

        # Check if we should suggest saving this loop
        suggestion = self.tracker.get_suggestion(proposal)
        if suggestion:
            logger.info(
                f"Suggesting to save loop: {suggestion.suggested_name} "
                f"(success_rate={suggestion.success_rate:.2f})"
            )

        return response

    async def execute_proposed_loop(self, request: TaskRequest) -> TaskResponse:
        """Propose and execute a custom loop for a task.

        High-level entry point for loop proposal execution.
        Proposes a loop, validates it, and executes it.

        Args:
            request: The task request

        Returns:
            TaskResponse with results
        """
        logger.info(f"Proposing loop for task {request.id}")

        # Propose the loop
        proposal = await self.propose_loop(request.query)

        # Validate
        validation = self.validate_loop_proposal(proposal)
        if not validation.valid:
            logger.error(f"Invalid loop proposal: {validation.errors}")
            # Fall back to novel arrangement
            return await self.execute_novel(request)

        if validation.warnings:
            for warning in validation.warnings:
                logger.warning(f"Loop proposal warning: {warning}")

        logger.info(
            f"Executing proposed loop: name={proposal.name}, "
            f"phases={len(proposal.phases)}"
        )

        # Execute the loop
        return await self.execute_loop_proposal(proposal, request)
