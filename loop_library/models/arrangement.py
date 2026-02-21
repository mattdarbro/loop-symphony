"""Models for novel arrangement generation (Phase 3A)."""

from typing import Literal

from pydantic import BaseModel, Field

from loop_library.models.instrument_config import InstrumentConfig


class ArrangementStep(BaseModel):
    """A single step in a sequential arrangement."""

    instrument: str = Field(description="Name of the instrument to use")
    config: InstrumentConfig | None = Field(
        default=None,
        description="Optional configuration overrides for this step",
    )


class ArrangementProposal(BaseModel):
    """Proposed arrangement from the planner."""

    type: Literal["sequential", "parallel", "single"] = Field(
        description="Composition type: sequential pipeline, parallel fan-out, or single instrument"
    )
    rationale: str = Field(
        description="Explanation of why this arrangement fits the task"
    )
    termination_criteria: str = Field(
        description="How we know when the task is complete"
    )
    steps: list[ArrangementStep] | None = Field(default=None)
    branches: list[str] | None = Field(default=None)
    merge_instrument: str = Field(default="synthesis")
    timeout_seconds: float | None = Field(default=None)
    instrument: str | None = Field(default=None)


class ArrangementValidation(BaseModel):
    """Result of validating an arrangement proposal."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
