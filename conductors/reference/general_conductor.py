"""GeneralConductor — reference implementation of BaseConductor.

Extracts the routing logic from the original server conductor.py and
re-implements it on top of the BaseConductor template method.
"""

from __future__ import annotations

import logging
import re
import time

from loop_library.instruments import (
    BaseInstrument,
    FalconInstrument,
    InstrumentResult,
    NoteInstrument,
    ResearchInstrument,
    SynthesisInstrument,
    VisionInstrument,
)
from loop_library.instruments.magenta import (
    DiagnoseInstrument,
    IngestInstrument,
    PrescribeInstrument,
    ReportInstrument,
    TrackInstrument,
)
from loop_library.models.finding import ExecutionMetadata
from loop_library.models.process import ProcessType
from loop_library.models.task import TaskContext, TaskRequest, TaskResponse
from loop_library.tools.registry import ToolRegistry

from conductors.base import BaseConductor
from conductors.models import ConductorConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing constants (mirrored from the original conductor.py)
# ---------------------------------------------------------------------------

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

COMPLEX_PATTERNS = [
    r"\band\b.*\band\b",
    r"\bvs\.?\b",
    r"\bversus\b",
    r"\bdifference between\b",
    r"\bpros and cons\b",
    r"\badvantages\b.*\bdisadvantages\b",
]

MAGENTA_KEYWORDS = [
    "magenta",
    "content analytics",
    "youtube analytics",
    "video performance",
    "retention curve",
    "content diagnosis",
    "content report",
    "creator analytics",
    "video analytics",
    "channel performance",
]

FALCON_KEYWORDS = [
    "shell:",
    "claude:",
    "on the falcon",
    "on falcon",
    "falcon ",
    "check disk",
    "check memory",
    "system info",
    "list files",
    "open browser",
    "browse to",
]

_IMAGE_INDICATORS = ("data:image/", ".jpg", ".jpeg", ".png", ".gif", ".webp")

_INSTRUMENT_PROCESS_TYPE: dict[str, ProcessType] = {
    "note": ProcessType.AUTONOMIC,
    "research": ProcessType.SEMI_AUTONOMIC,
    "synthesis": ProcessType.SEMI_AUTONOMIC,
    "vision": ProcessType.SEMI_AUTONOMIC,
    "falcon": ProcessType.SEMI_AUTONOMIC,
    "magenta_ingest": ProcessType.CONSCIOUS,
    "magenta_diagnose": ProcessType.CONSCIOUS,
    "magenta_prescribe": ProcessType.CONSCIOUS,
    "magenta_track": ProcessType.CONSCIOUS,
    "magenta_report": ProcessType.CONSCIOUS,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# GeneralConductor
# ---------------------------------------------------------------------------


class GeneralConductor(BaseConductor):
    """Reference conductor that mirrors the original server Conductor routing.

    This class demonstrates how to implement the ``BaseConductor`` pattern
    while preserving the exact routing heuristics from the original
    ``conductor.py``.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        config: ConductorConfig | None = None,
    ) -> None:
        if config is None:
            config = ConductorConfig(
                name="general",
                description="General-purpose conductor with keyword-based routing",
            )

        self.registry = registry

        # Build instruments dict (same logic as original Conductor.__init__)
        if registry is not None:
            instruments: dict[str, BaseInstrument] = {
                "note": self._build_instrument("note"),
                "research": self._build_instrument("research"),
                "synthesis": self._build_instrument("synthesis"),
                "vision": self._build_instrument("vision"),
                "falcon": FalconInstrument(),
                "magenta_ingest": self._build_instrument("magenta_ingest"),
                "magenta_diagnose": self._build_instrument("magenta_diagnose"),
                "magenta_prescribe": self._build_instrument("magenta_prescribe"),
                "magenta_track": self._build_instrument("magenta_track"),
                "magenta_report": self._build_instrument("magenta_report"),
            }
        else:
            instruments = {
                "note": NoteInstrument(),
                "research": ResearchInstrument(),
                "synthesis": SynthesisInstrument(),
                "vision": VisionInstrument(),
                "falcon": FalconInstrument(),
                "magenta_ingest": IngestInstrument(),
                "magenta_diagnose": DiagnoseInstrument(),
                "magenta_prescribe": PrescribeInstrument(),
                "magenta_track": TrackInstrument(),
                "magenta_report": ReportInstrument(),
            }

        super().__init__(config, instruments)

    # ------------------------------------------------------------------
    # Instrument builder (uses ToolRegistry when available)
    # ------------------------------------------------------------------

    def _build_instrument(self, name: str) -> BaseInstrument:
        """Build an instrument with tools resolved from the registry."""
        if self.registry is None:
            raise ValueError("Cannot build instrument without a ToolRegistry")

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
        elif name == "magenta_ingest":
            tools = self.registry.resolve(IngestInstrument.required_capabilities)
            return IngestInstrument(claude=tools["reasoning"])
        elif name == "magenta_diagnose":
            tools = self.registry.resolve(DiagnoseInstrument.required_capabilities)
            return DiagnoseInstrument(claude=tools["reasoning"])
        elif name == "magenta_prescribe":
            tools = self.registry.resolve(PrescribeInstrument.required_capabilities)
            return PrescribeInstrument(claude=tools["reasoning"])
        elif name == "magenta_track":
            tools = self.registry.resolve(TrackInstrument.required_capabilities)
            return TrackInstrument(claude=tools["reasoning"])
        elif name == "magenta_report":
            tools = self.registry.resolve(ReportInstrument.required_capabilities)
            return ReportInstrument(claude=tools["reasoning"])
        raise ValueError(f"Unknown instrument: {name}")

    # ------------------------------------------------------------------
    # BaseConductor hooks
    # ------------------------------------------------------------------

    async def route(self, request: TaskRequest) -> str:
        """Analyze task and determine which instrument to use.

        Routing rules (evaluated in order):
        1. Image attachments in context -> ``vision``
        2. Falcon/execution keywords -> ``falcon``
        3. Magenta/content-analytics keywords -> ``magenta_ingest``
        4. Research keywords -> ``research``
        5. Complex regex patterns -> ``research``
        6. Long queries (>20 words) -> ``research``
        7. Multiple question marks -> ``research``
        8. Thoroughness preference == "thorough" -> ``research``
        9. Default -> ``note``

        Args:
            request: The incoming task request.

        Returns:
            Name of the instrument to route to.
        """
        query = request.query.lower()

        # 1. Vision: image attachments
        if _has_image_attachments(request.context):
            logger.debug("Routing to vision: image attachments detected")
            return "vision"

        # 2. Falcon / execution keywords
        for keyword in FALCON_KEYWORDS:
            if keyword in query:
                logger.debug(f"Routing to falcon: keyword '{keyword}' found")
                return "falcon"

        # 3. Magenta / content analytics keywords
        for keyword in MAGENTA_KEYWORDS:
            if keyword in query:
                logger.debug(f"Routing to magenta_ingest: keyword '{keyword}' found")
                return "magenta_ingest"

        # 4. Research keywords
        for keyword in RESEARCH_KEYWORDS:
            if keyword in query:
                logger.debug(f"Routing to research: keyword '{keyword}' found")
                return "research"

        # 5. Complex patterns
        for pattern in COMPLEX_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                logger.debug("Routing to research: complex pattern found")
                return "research"

        # 6. Long queries
        word_count = len(query.split())
        if word_count > 20:
            logger.debug(f"Routing to research: long query ({word_count} words)")
            return "research"

        # 7. Multiple question marks
        question_count = query.count("?")
        if question_count > 1:
            logger.debug(
                f"Routing to research: multiple questions ({question_count})"
            )
            return "research"

        # 8. Thoroughness preference
        if request.preferences and request.preferences.thoroughness == "thorough":
            logger.debug("Routing to research: thorough preference")
            return "research"

        # 9. Default to note
        logger.debug("Routing to note: simple query")
        return "note"

    async def interpret_results(
        self,
        request: TaskRequest,
        result: InstrumentResult,
        instrument_name: str,
    ) -> TaskResponse:
        """Wrap an InstrumentResult into a TaskResponse with metadata.

        The ``process_type`` is looked up from ``_INSTRUMENT_PROCESS_TYPE``,
        defaulting to ``SEMI_AUTONOMIC`` for unknown instruments.

        Args:
            request: The original task request.
            result: Raw result from the instrument.
            instrument_name: Which instrument produced the result.

        Returns:
            A fully-populated ``TaskResponse``.
        """
        process_type = _INSTRUMENT_PROCESS_TYPE.get(
            instrument_name, ProcessType.SEMI_AUTONOMIC
        )

        return TaskResponse(
            request_id=request.id,
            outcome=result.outcome,
            findings=result.findings,
            summary=result.summary,
            confidence=result.confidence,
            metadata=ExecutionMetadata(
                instrument_used=instrument_name,
                iterations=result.iterations,
                duration_ms=0,  # Duration tracked by handle() callers
                sources_consulted=result.sources_consulted,
                process_type=process_type,
            ),
            discrepancy=result.discrepancy,
            suggested_followups=result.suggested_followups,
        )
