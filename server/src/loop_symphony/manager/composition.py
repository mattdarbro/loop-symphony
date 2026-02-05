"""Composition patterns for orchestrating instrument pipelines."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.models.instrument_config import InstrumentConfig
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext

if TYPE_CHECKING:
    from loop_symphony.manager.conductor import Conductor

logger = logging.getLogger(__name__)


class SequentialComposition:
    """Executes a sequence of instrument steps as a pipeline.

    Each step's InstrumentResult is serialized and passed as
    context.input_results to the next step. This enables patterns
    like research -> synthesis where the synthesis step merges
    the research findings.

    Early termination: if any step returns Outcome.INCONCLUSIVE,
    the pipeline stops and returns that step's result.
    """

    def __init__(
        self,
        steps: list[tuple[str, InstrumentConfig | None]],
    ) -> None:
        if not steps:
            raise ValueError("SequentialComposition requires at least one step")
        self.steps = steps

    @property
    def name(self) -> str:
        """Human-readable name built from step instrument names."""
        return " -> ".join(instrument_name for instrument_name, _ in self.steps)

    async def execute(
        self,
        query: str,
        context: TaskContext | None,
        conductor: Conductor,
    ) -> InstrumentResult:
        """Execute all steps sequentially.

        Args:
            query: The user's query
            context: Optional task context (cloned per step)
            conductor: Reference to the Conductor for instrument access

        Returns:
            InstrumentResult from the final step (or the step that
            caused early termination)
        """
        logger.info(
            f"Sequential composition '{self.name}' starting "
            f"with {len(self.steps)} steps"
        )

        total_iterations = 0
        all_sources: list[str] = []
        previous_results: list[dict] | None = None
        last_result: InstrumentResult | None = None

        for step_index, (instrument_name, config) in enumerate(self.steps):
            logger.info(
                f"Composition step {step_index + 1}/{len(self.steps)}: "
                f"{instrument_name}"
            )

            instrument = conductor.instruments.get(instrument_name)
            if instrument is None:
                raise ValueError(
                    f"Unknown instrument '{instrument_name}' in composition "
                    f"step {step_index + 1}"
                )

            # Apply config overrides, saving originals for restoration
            originals = _apply_config(instrument, config)

            try:
                step_context = _build_step_context(context, previous_results)
                result = await instrument.execute(query, step_context)
            finally:
                _restore_config(instrument, originals)

            # Accumulate metadata
            total_iterations += result.iterations
            all_sources.extend(result.sources_consulted)
            last_result = result

            logger.info(
                f"Step {step_index + 1} complete: "
                f"outcome={result.outcome.value}, "
                f"confidence={result.confidence:.2f}"
            )

            # Early termination on INCONCLUSIVE
            if result.outcome == Outcome.INCONCLUSIVE:
                logger.info(
                    f"Early termination at step {step_index + 1}: INCONCLUSIVE"
                )
                break

            # Serialize result for next step's input_results
            previous_results = [_serialize_result(result)]

        assert last_result is not None  # guaranteed by non-empty steps

        return InstrumentResult(
            outcome=last_result.outcome,
            findings=last_result.findings,
            summary=last_result.summary,
            confidence=last_result.confidence,
            iterations=total_iterations,
            sources_consulted=sorted(set(all_sources)),
            discrepancy=last_result.discrepancy,
            suggested_followups=last_result.suggested_followups,
        )


class ParallelComposition:
    """Executes multiple instrument branches in parallel and merges results.

    Fan-out: launches N branches concurrently via asyncio.gather().
    Fan-in: collects successful results and passes them to a merge
    instrument (default: synthesis) as context.input_results.

    Supports per-branch timeout and partial failure handling.
    If all branches fail, returns INCONCLUSIVE.
    """

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
        """Human-readable name built from branch and merge instrument names."""
        branch_str = " | ".join(self.branches)
        return f"parallel({branch_str}) -> {self.merge_instrument}"

    async def execute(
        self,
        query: str,
        context: TaskContext | None,
        conductor: Conductor,
    ) -> InstrumentResult:
        """Execute all branches in parallel, then merge results.

        Args:
            query: The user's query
            context: Optional task context (cloned per branch)
            conductor: Reference to the Conductor for instrument access

        Returns:
            InstrumentResult from the merge step, or INCONCLUSIVE if
            all branches failed
        """
        logger.info(
            f"Parallel composition '{self.name}' starting "
            f"with {len(self.branches)} branches"
        )

        # Validate all instruments exist
        for branch_name in self.branches:
            if branch_name not in conductor.instruments:
                raise ValueError(
                    f"Unknown instrument '{branch_name}' in parallel composition"
                )
        if self.merge_instrument not in conductor.instruments:
            raise ValueError(
                f"Unknown merge instrument '{self.merge_instrument}' "
                f"in parallel composition"
            )

        # Build branch context (no input_results for branches)
        branch_context = _build_step_context(context, None)

        # Fan-out: launch all branches concurrently
        coros = [
            self._run_branch(
                conductor.instruments[name], query, branch_context
            )
            for name in self.branches
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Separate successes from failures
        successful: list[InstrumentResult] = []
        failed: list[tuple[str, str]] = []
        total_iterations = 0
        all_sources: list[str] = []

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                failed.append((self.branches[i], str(result)))
                logger.warning(
                    f"Branch '{self.branches[i]}' failed: {result}"
                )
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

        # Fan-in: serialize successful results and pass to merge instrument
        serialized = [_serialize_result(r) for r in successful]
        merge_context = _build_step_context(context, serialized)
        merge_instrument = conductor.instruments[self.merge_instrument]
        merge_result = await merge_instrument.execute(query, merge_context)

        total_iterations += merge_result.iterations
        all_sources.extend(merge_result.sources_consulted)

        # Combine discrepancy info
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
        self,
        instrument: object,
        query: str,
        context: TaskContext,
    ) -> InstrumentResult:
        """Run a single branch with optional timeout."""
        if self.timeout_seconds is not None:
            return await asyncio.wait_for(
                instrument.execute(query, context),
                timeout=self.timeout_seconds,
            )
        return await instrument.execute(query, context)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _serialize_result(result: InstrumentResult) -> dict:
    """Convert an InstrumentResult to a dict for context.input_results.

    Format matches what SynthesisInstrument._collect_findings() expects.
    """
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


def _build_step_context(
    base_context: TaskContext | None,
    input_results: list[dict] | None,
) -> TaskContext:
    """Build a TaskContext for a composition step.

    Clones the base context (if any) and sets input_results.
    """
    if base_context is not None:
        return base_context.model_copy(update={"input_results": input_results})
    return TaskContext(input_results=input_results)


def _apply_config(
    instrument: object,
    config: InstrumentConfig | None,
) -> dict[str, object]:
    """Apply InstrumentConfig overrides to an instrument instance.

    Returns a dict of original values for restoration via _restore_config.
    """
    if config is None:
        return {}

    originals: dict[str, object] = {}

    if config.max_iterations is not None and hasattr(instrument, "max_iterations"):
        originals["max_iterations"] = getattr(instrument, "max_iterations")
        instrument.max_iterations = config.max_iterations

    if config.confidence_threshold is not None:
        if hasattr(instrument, "termination"):
            term = instrument.termination
            if hasattr(term, "confidence_threshold"):
                originals["termination.confidence_threshold"] = (
                    term.confidence_threshold
                )
                term.confidence_threshold = config.confidence_threshold

    if config.confidence_delta_threshold is not None:
        if hasattr(instrument, "termination"):
            term = instrument.termination
            if hasattr(term, "confidence_delta_threshold"):
                originals["termination.confidence_delta_threshold"] = (
                    term.confidence_delta_threshold
                )
                term.confidence_delta_threshold = config.confidence_delta_threshold

    return originals


def _restore_config(
    instrument: object,
    originals: dict[str, object],
) -> None:
    """Restore original config values saved by _apply_config."""
    for key, value in originals.items():
        if "." in key:
            parts = key.split(".")
            obj = instrument
            for part in parts[:-1]:
                obj = getattr(obj, part)
            setattr(obj, parts[-1], value)
        else:
            setattr(instrument, key, value)
