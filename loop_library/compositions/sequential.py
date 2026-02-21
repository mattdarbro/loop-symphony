"""Sequential composition pattern."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.instrument_config import InstrumentConfig
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.compositions.helpers import (
    _apply_config,
    _build_step_context,
    _restore_config,
    _serialize_result,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class InstrumentProvider(Protocol):
    """Protocol for objects that provide instrument lookup."""
    instruments: dict[str, BaseInstrument]


class SequentialComposition:
    """Executes a sequence of instrument steps as a pipeline."""

    def __init__(
        self,
        steps: list[tuple[str, InstrumentConfig | None]],
    ) -> None:
        if not steps:
            raise ValueError("SequentialComposition requires at least one step")
        self.steps = steps

    @property
    def name(self) -> str:
        return " -> ".join(instrument_name for instrument_name, _ in self.steps)

    async def execute(
        self,
        query: str,
        context: TaskContext | None,
        conductor: InstrumentProvider,
    ) -> InstrumentResult:
        """Execute all steps sequentially."""
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

            originals = _apply_config(instrument, config)

            try:
                step_context = _build_step_context(context, previous_results)
                result = await instrument.execute(query, step_context)
            finally:
                _restore_config(instrument, originals)

            total_iterations += result.iterations
            all_sources.extend(result.sources_consulted)
            last_result = result

            logger.info(
                f"Step {step_index + 1} complete: "
                f"outcome={result.outcome.value}, "
                f"confidence={result.confidence:.2f}"
            )

            if result.outcome == Outcome.INCONCLUSIVE:
                logger.info(f"Early termination at step {step_index + 1}: INCONCLUSIVE")
                break

            previous_results = [_serialize_result(result)]

        assert last_result is not None

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
