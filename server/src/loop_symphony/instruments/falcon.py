"""Falcon instrument - delegates execution to the Falcon Tower room.

This instrument doesn't execute locally. It exists so the Conductor's
routing logic can identify tasks that need shell_execution capability
and delegate them to the Falcon room via the room registry.

If no Falcon room is registered, the instrument returns BOUNDED with
a message explaining the capability is unavailable.
"""

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext


class FalconInstrument(BaseInstrument):
    """Instrument stub for Falcon Tower delegation.

    Required capability: shell_execution — only the Falcon room provides this.
    The Conductor's _select_room() will match this capability to the Falcon
    room and delegate via _delegate_to_room() before this execute() is called.

    If execute() IS called, it means no Falcon room was available, so we
    return a BOUNDED result explaining the situation.
    """

    name = "falcon"
    max_iterations = 1
    required_capabilities = frozenset({"shell_execution"})
    optional_capabilities = frozenset()

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        """Fallback when Falcon room is not available.

        This only runs if room delegation was skipped or failed.
        """
        return InstrumentResult(
            outcome=Outcome.BOUNDED,
            findings=[
                Finding(
                    content="This task requires the Falcon Tower room for shell execution, "
                    "but it is not currently available.",
                    confidence=1.0,
                    source="falcon_instrument",
                )
            ],
            summary="The Falcon Tower room is required for this task but is not online. "
            "Please ensure the Falcon room is registered and accessible.",
            confidence=0.0,
            iterations=1,
            sources_consulted=[],
            suggested_followups=[
                "Check if the Falcon Tower is running and registered",
                "Try again when the Falcon room is online",
            ],
        )
