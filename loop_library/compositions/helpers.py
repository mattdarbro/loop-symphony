"""Shared helpers for composition patterns."""

from loop_library.instruments.base import InstrumentResult
from loop_library.models.instrument_config import InstrumentConfig
from loop_library.models.task import TaskContext


def _serialize_result(result: InstrumentResult) -> dict:
    """Convert an InstrumentResult to a dict for context.input_results."""
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
    """Build a TaskContext for a composition step."""
    if base_context is not None:
        return base_context.model_copy(update={"input_results": input_results})
    return TaskContext(input_results=input_results)


def _apply_config(
    instrument: object,
    config: InstrumentConfig | None,
) -> dict[str, object]:
    """Apply InstrumentConfig overrides to an instrument instance."""
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
                originals["termination.confidence_threshold"] = term.confidence_threshold
                term.confidence_threshold = config.confidence_threshold

    if config.confidence_delta_threshold is not None:
        if hasattr(instrument, "termination"):
            term = instrument.termination
            if hasattr(term, "confidence_delta_threshold"):
                originals["termination.confidence_delta_threshold"] = term.confidence_delta_threshold
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
