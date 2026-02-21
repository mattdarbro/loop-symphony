"""Falcon instrument - delegates execution tasks to the Falcon Tower room."""

import logging

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext

logger = logging.getLogger(__name__)


class FalconInstrument(BaseInstrument):
    """Falcon instrument for tasks requiring local machine execution.

    Routes to the Falcon Tower room for shell commands, file system ops, etc.
    This is a passthrough — actual execution happens via room delegation.
    """

    name = "falcon"
    max_iterations = 1
    required_capabilities = frozenset({"shell_execution"})

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        """Fallback execution if room delegation fails."""
        logger.warning(
            f"Falcon instrument execute() called directly for: {query[:50]}... "
            "This means room delegation failed or was skipped."
        )

        return InstrumentResult(
            outcome=Outcome.BOUNDED,
            findings=[
                Finding(
                    content="This task requires the Falcon Tower room but it appears to be offline or unreachable.",
                    source="falcon_instrument",
                    confidence=0.3,
                )
            ],
            summary="Falcon Tower room is not available. Please check that the Falcon is online and the tunnel is running.",
            confidence=0.3,
            iterations=1,
            sources_consulted=["falcon_instrument"],
            suggested_followups=[
                "[proactive] The Falcon Tower room may be offline. Check the room status at /rooms",
            ],
        )
