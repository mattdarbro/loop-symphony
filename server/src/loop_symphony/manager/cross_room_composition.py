"""Cross-room parallel composition (Phase 4C).

Fans out sub-tasks across multiple rooms simultaneously,
then merges results via a synthesis instrument.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext, TaskRequest

if TYPE_CHECKING:
    from loop_symphony.manager.conductor import Conductor

logger = logging.getLogger(__name__)


@dataclass
class RoomBranch:
    """A single branch in a cross-room composition.

    Defines a sub-query to run on a specific or auto-selected room.
    """

    query: str
    room_id: str | None = None  # Specific room, or None for auto-select
    instrument: str | None = None  # Specific instrument, or None for auto-route
    required_capabilities: set[str] = field(default_factory=set)
    prefer_local: bool = False  # Privacy hint — prefer local room


class CrossRoomComposition:
    """Execute sub-tasks across multiple rooms in parallel.

    Fan-out: send sub-tasks to assigned rooms concurrently.
    Fan-in: collect results, merge via synthesis instrument.
    Graceful degradation: on room failure, skip or fall back to server.

    Follows the same duck-typed interface as SequentialComposition
    and ParallelComposition (name property + execute method).
    """

    def __init__(
        self,
        branches: list[RoomBranch],
        *,
        merge_instrument: str = "synthesis",
        timeout_seconds: float = 120.0,
    ) -> None:
        """Initialize the cross-room composition.

        Args:
            branches: Sub-tasks with room assignment hints
            merge_instrument: Instrument to merge branch results
            timeout_seconds: Per-branch timeout
        """
        if not branches:
            raise ValueError("CrossRoomComposition requires at least one branch")
        self.branches = branches
        self.merge_instrument = merge_instrument
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Human-readable name built from branch descriptions."""
        branch_descs = []
        for b in self.branches:
            room = b.room_id or "auto"
            branch_descs.append(f"{room}:{b.query[:30]}")
        return f"cross_room({' | '.join(branch_descs)}) -> {self.merge_instrument}"

    async def execute(
        self,
        query: str,
        context: TaskContext | None,
        conductor: Conductor,
    ) -> InstrumentResult:
        """Execute all branches across rooms, then merge.

        For each branch:
        - If room_id is specified and exists, delegate to that room
        - If room_id is None, use conductor's room selection logic
        - Server branches execute locally via conductor's instruments
        - Remote branches delegate via RoomClient

        Args:
            query: The original query (used for merge step)
            context: Optional task context
            conductor: Reference to the Conductor

        Returns:
            InstrumentResult from the merge step
        """
        logger.info(
            f"Cross-room composition starting with {len(self.branches)} branches"
        )

        # Launch all branches concurrently
        coros = [
            self._run_branch(branch, context, conductor)
            for branch in self.branches
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Separate successes from failures
        successful: list[InstrumentResult] = []
        failed: list[tuple[str, str]] = []
        total_iterations = 0
        all_sources: list[str] = []

        for i, result in enumerate(results):
            branch = self.branches[i]
            label = branch.room_id or f"branch-{i}"

            if isinstance(result, BaseException):
                failed.append((label, str(result)))
                logger.warning(f"Branch '{label}' failed: {result}")
            else:
                successful.append(result)
                total_iterations += result.iterations
                all_sources.extend(result.sources_consulted)

        failure_note = (
            "; ".join(f"{name}: {err}" for name, err in failed)
            if failed
            else None
        )

        # All-fail case
        if not successful:
            logger.info("All cross-room branches failed")
            return InstrumentResult(
                outcome=Outcome.INCONCLUSIVE,
                findings=[],
                summary=f"All {len(self.branches)} cross-room branches failed",
                confidence=0.0,
                iterations=0,
                discrepancy=failure_note,
            )

        # Single success — return directly (no merge needed)
        if len(successful) == 1 and not failed:
            return successful[0]

        logger.info(
            f"{len(successful)}/{len(self.branches)} branches succeeded, "
            f"merging via {self.merge_instrument}"
        )

        # Fan-in: serialize results and pass to merge instrument
        serialized = [self._serialize_result(r) for r in successful]
        merge_context = self._build_merge_context(context, serialized)

        if self.merge_instrument not in conductor.instruments:
            raise ValueError(
                f"Unknown merge instrument '{self.merge_instrument}'"
            )

        merge_instrument = conductor.instruments[self.merge_instrument]
        merge_result = await merge_instrument.execute(query, merge_context)

        total_iterations += merge_result.iterations
        all_sources.extend(merge_result.sources_consulted)

        # Combine discrepancy info
        combined_discrepancy = merge_result.discrepancy
        if failure_note:
            branch_warning = f"Room failures: {failure_note}"
            combined_discrepancy = (
                f"{branch_warning}; {combined_discrepancy}"
                if combined_discrepancy
                else branch_warning
            )

        return InstrumentResult(
            outcome=merge_result.outcome,
            findings=merge_result.findings,
            summary=merge_result.summary,
            confidence=merge_result.confidence,
            iterations=total_iterations,
            sources_consulted=sorted(set(all_sources)),
            discrepancy=combined_discrepancy,
            suggested_followups=merge_result.suggested_followups,
        )

    async def _run_branch(
        self,
        branch: RoomBranch,
        context: TaskContext | None,
        conductor: Conductor,
    ) -> InstrumentResult:
        """Run a single branch, routing to the appropriate room.

        Args:
            branch: The branch definition
            context: Optional task context
            conductor: The conductor for room resolution

        Returns:
            InstrumentResult from the branch execution
        """
        # Determine target room
        room = None
        if conductor.room_registry is not None:
            if branch.room_id:
                room = conductor.room_registry.get_room(branch.room_id)
            else:
                # Auto-select based on capabilities and privacy hint
                room = conductor.room_registry.get_best_room_for_task(
                    required_capabilities=branch.required_capabilities or None,
                    preferred_room_type="local" if branch.prefer_local else None,
                    prefer_local=branch.prefer_local,
                )

        # If room is remote, delegate
        if room and room.room_type != "server":
            request = TaskRequest(query=branch.query, context=context)
            delegated = await conductor._delegate_to_room(room, request)
            if delegated is not None:
                # Convert TaskResponse back to InstrumentResult
                return InstrumentResult(
                    outcome=delegated.outcome,
                    findings=delegated.findings,
                    summary=delegated.summary,
                    confidence=delegated.confidence,
                    iterations=delegated.metadata.iterations if delegated.metadata else 1,
                    sources_consulted=(
                        delegated.metadata.sources_consulted if delegated.metadata else []
                    ),
                )
            logger.warning(
                f"Delegation to {room.room_id} failed for branch, "
                f"falling back to server"
            )

        # Server execution (local or fallback)
        instrument_name = branch.instrument
        if instrument_name is None:
            # Auto-route using the conductor's logic
            request = TaskRequest(query=branch.query, context=context)
            instrument_name = await conductor.analyze_and_route(request)

        if instrument_name not in conductor.instruments:
            raise ValueError(f"Unknown instrument '{instrument_name}' in branch")

        instrument = conductor.instruments[instrument_name]
        branch_context = context.model_copy() if context else TaskContext()

        coro = instrument.execute(branch.query, branch_context)
        if self.timeout_seconds is not None:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        return await coro

    @staticmethod
    def _serialize_result(result: InstrumentResult) -> dict:
        """Convert an InstrumentResult to a dict for merge input."""
        return {
            "outcome": result.outcome.value,
            "findings": [f.model_dump(mode="json") for f in result.findings],
            "summary": result.summary,
            "confidence": result.confidence,
            "iterations": result.iterations,
            "sources_consulted": result.sources_consulted,
            "discrepancy": result.discrepancy,
            "suggested_followups": result.suggested_followups,
        }

    @staticmethod
    def _build_merge_context(
        base_context: TaskContext | None,
        input_results: list[dict],
    ) -> TaskContext:
        """Build context for the merge step."""
        if base_context is not None:
            return base_context.model_copy(update={"input_results": input_results})
        return TaskContext(input_results=input_results)
