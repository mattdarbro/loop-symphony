"""Parallel composition pattern."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.compositions.helpers import _build_step_context, _serialize_result

logger = logging.getLogger(__name__)


@runtime_checkable
class InstrumentProvider(Protocol):
    """Protocol for objects that provide instrument lookup."""
    instruments: dict[str, BaseInstrument]


class ParallelComposition:
    """Executes multiple instrument branches in parallel and merges results."""

    def __init__(
        self,
        branches: list[str],
        *,
        merge_instrument: str = "synthesis",
        timeout_seconds: float | None = None,
    ) -> None:
        if not branches:
            raise ValueError("ParallelComposition requires at least one branch")
        self.branches = branches
        self.merge_instrument = merge_instrument
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        branch_str = " | ".join(self.branches)
        return f"parallel({branch_str}) -> {self.merge_instrument}"

    async def execute(
        self,
        query: str,
        context: TaskContext | None,
        conductor: InstrumentProvider,
    ) -> InstrumentResult:
        """Execute all branches in parallel, then merge results."""
        logger.info(
            f"Parallel composition '{self.name}' starting "
            f"with {len(self.branches)} branches"
        )

        for branch_name in self.branches:
            if branch_name not in conductor.instruments:
                raise ValueError(f"Unknown instrument '{branch_name}' in parallel composition")
        if self.merge_instrument not in conductor.instruments:
            raise ValueError(f"Unknown merge instrument '{self.merge_instrument}'")

        branch_context = _build_step_context(context, None)

        coros = [
            self._run_branch(conductor.instruments[name], query, branch_context)
            for name in self.branches
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        successful: list[InstrumentResult] = []
        failed: list[tuple[str, str]] = []
        total_iterations = 0
        all_sources: list[str] = []

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                failed.append((self.branches[i], str(result)))
                logger.warning(f"Branch '{self.branches[i]}' failed: {result}")
            else:
                successful.append(result)
                total_iterations += result.iterations
                all_sources.extend(result.sources_consulted)

        failure_note = (
            "; ".join(f"{name}: {err}" for name, err in failed)
            if failed else None
        )

        if not successful:
            logger.info("All parallel branches failed")
            return InstrumentResult(
                outcome=Outcome.INCONCLUSIVE,
                findings=[],
                summary=f"All {len(self.branches)} parallel branches failed",
                confidence=0.0,
                iterations=0,
                discrepancy=failure_note,
            )

        logger.info(
            f"{len(successful)}/{len(self.branches)} branches succeeded, "
            f"merging via {self.merge_instrument}"
        )

        serialized = [_serialize_result(r) for r in successful]
        merge_context = _build_step_context(context, serialized)
        merge_instrument = conductor.instruments[self.merge_instrument]
        merge_result = await merge_instrument.execute(query, merge_context)

        total_iterations += merge_result.iterations
        all_sources.extend(merge_result.sources_consulted)

        combined_discrepancy = merge_result.discrepancy
        if failure_note:
            branch_warning = f"Branch failures: {failure_note}"
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
        self, instrument: object, query: str, context: TaskContext,
    ) -> InstrumentResult:
        if self.timeout_seconds is not None:
            return await asyncio.wait_for(
                instrument.execute(query, context),
                timeout=self.timeout_seconds,
            )
        return await instrument.execute(query, context)
