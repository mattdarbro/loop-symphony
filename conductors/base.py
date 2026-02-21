"""Abstract BaseConductor — template method for task routing and execution."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from loop_library.exceptions import DepthExceededError
from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import ExecutionMetadata
from loop_library.models.process import ProcessType
from loop_library.models.task import TaskContext, TaskRequest, TaskResponse

from conductors.models import ConductorConfig, LoopInvocation

logger = logging.getLogger(__name__)


class BaseConductor(ABC):
    """Abstract base class for all conductors.

    Provides a template-method ``handle`` that:
    1. Manages recursion depth.
    2. Injects a ``spawn_fn`` callback for sub-task spawning.
    3. Delegates routing and result interpretation to subclass hooks.
    """

    def __init__(
        self,
        config: ConductorConfig,
        instruments: dict[str, BaseInstrument] | None = None,
    ) -> None:
        self.config = config
        self.instruments: dict[str, BaseInstrument] = instruments or {}

    # ------------------------------------------------------------------
    # Abstract hooks — subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    async def route(self, request: TaskRequest) -> str:
        """Determine which instrument should handle *request*.

        Args:
            request: The incoming task request.

        Returns:
            The name of the instrument to use (must be a key in
            ``self.instruments``).
        """
        ...

    @abstractmethod
    async def interpret_results(
        self,
        request: TaskRequest,
        result: InstrumentResult,
        instrument_name: str,
    ) -> TaskResponse:
        """Wrap an ``InstrumentResult`` into a full ``TaskResponse``.

        Args:
            request: The original task request.
            result: The raw result from instrument execution.
            instrument_name: Which instrument produced the result.

        Returns:
            A fully-populated ``TaskResponse``.
        """
        ...

    # ------------------------------------------------------------------
    # Template method
    # ------------------------------------------------------------------

    async def handle(self, request: TaskRequest) -> TaskResponse:
        """Execute a task request end-to-end (template method).

        Steps:
        1. Get or create context; enforce depth limit.
        2. Build a ``_spawn`` callback for recursive sub-tasks.
        3. Inject ``spawn_fn`` into the context.
        4. Route to an instrument via ``self.route()``.
        5. Execute the chosen instrument.
        6. Interpret the result via ``self.interpret_results()``.

        Args:
            request: The task request to execute.

        Returns:
            A ``TaskResponse`` with full results.

        Raises:
            DepthExceededError: If the current depth exceeds
                ``config.max_depth``.
        """
        # 1. Context & depth guard
        context = request.context or TaskContext()
        current_depth = context.depth
        max_depth = self.config.max_depth

        # Preference override for max depth
        if request.preferences and request.preferences.max_spawn_depth is not None:
            max_depth = request.preferences.max_spawn_depth

        if current_depth > max_depth:
            raise DepthExceededError(current_depth, max_depth)

        # 2. Build spawn callback
        async def _spawn(
            sub_query: str,
            sub_context: TaskContext | None = None,
        ) -> InstrumentResult:
            """Spawn a sub-task at incremented depth.

            Args:
                sub_query: The query for the sub-task.
                sub_context: Optional context to merge (e.g. input_results).

            Returns:
                InstrumentResult from the recursive execution.

            Raises:
                DepthExceededError: If spawning would exceed max_depth.
            """
            new_depth = current_depth + 1
            if new_depth > max_depth:
                raise DepthExceededError(new_depth, max_depth)

            # Build sub-context from current, merging optional overrides
            base = context.model_copy(
                update={
                    "depth": new_depth,
                    "max_depth": max_depth,
                    "spawn_fn": None,  # Re-injected by recursive call
                }
            )

            if sub_context is not None:
                merge: dict = {}
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

            # Recursive execution through the same conductor
            sub_response = await self.handle(sub_request)

            # Convert TaskResponse back to InstrumentResult
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

        # 3. Inject spawn_fn into context
        enriched_context = context.model_copy(
            update={
                "spawn_fn": _spawn,
                "depth": current_depth,
                "max_depth": max_depth,
            }
        )
        request = request.model_copy(update={"context": enriched_context})

        # 4. Route to instrument
        instrument_name = await self.route(request)

        logger.info(
            f"Executing task {request.id} with {instrument_name} instrument "
            f"(depth={current_depth}/{max_depth})"
        )

        # 5. Execute instrument
        instrument = self.instruments[instrument_name]
        result: InstrumentResult = await instrument.execute(
            request.query,
            request.context,
        )

        # 6. Interpret & return
        return await self.interpret_results(request, result, instrument_name)
