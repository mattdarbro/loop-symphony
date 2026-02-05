"""Conductor - task analysis and instrument routing."""

import logging
import re
import time

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.instruments.note import NoteInstrument
from loop_symphony.instruments.research import ResearchInstrument
from loop_symphony.instruments.synthesis import SynthesisInstrument
from loop_symphony.instruments.vision import VisionInstrument
from loop_symphony.models.finding import ExecutionMetadata
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskContext, TaskRequest, TaskResponse
from loop_symphony.tools.registry import ToolRegistry

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
    """

    def __init__(self, *, registry: ToolRegistry | None = None) -> None:
        self.registry = registry
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

        # Route to appropriate instrument
        instrument_name = await self.analyze_and_route(request)
        instrument = self.instruments[instrument_name]

        logger.info(f"Executing task {request.id} with {instrument_name} instrument")

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
