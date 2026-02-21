"""Per-step instrument configuration for compositions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentConfig:
    """Runtime overrides for instrument execution within a composition step.

    All fields are optional. When None, the instrument uses its own defaults.
    Frozen to prevent accidental mutation of shared config objects.
    """

    max_iterations: int | None = None
    confidence_threshold: float | None = None
    confidence_delta_threshold: float | None = None
