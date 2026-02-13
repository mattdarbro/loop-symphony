"""Falcon instrument - delegates execution tasks to the Falcon Tower room.

This is a passthrough instrument. Unlike note/research/synthesis which
execute locally on the server, the falcon instrument signals to the
Conductor that this task should be delegated to the Falcon Tower room.

The actual execution happens on the Falcon via the RoomClient delegation
flow already built in Phase 4C.
"""

import logging

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext

logger = logging.getLogger(__name__)


class FalconInstrument(BaseInstrument):
    """Falcon instrument for tasks requiring local machine execution.

    Routes to the Falcon Tower room for:
    - Shell command execution
    - File system operations
    - Claude Code tasks
    - Browser automation
    - Long-running processes

    The Conductor's room selection logic will match this instrument's
    required_capabilities to the Falcon room's advertised capabilities,
    causing automatic delegation via RoomClient.
    """

    name = "falcon"
    max_iterations = 1
    required_capabilities = frozenset({"shell_execution"})

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        """Fallback execution if room delegation fails.

        This should rarely be called directly — the Conductor will
        normally delegate to the Falcon room via RoomClient before
        reaching this method. This exists as a safety net.

        Args:
            query: The user's query
            context: Optional task context

        Returns:
            InstrumentResult indicating delegation was expected
        """
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
