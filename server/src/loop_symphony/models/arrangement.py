"""Models for novel arrangement generation (Phase 3A)."""

from typing import Literal

from pydantic import BaseModel, Field

from loop_symphony.models.instrument_config import InstrumentConfig


class ArrangementStep(BaseModel):
    """A single step in a sequential arrangement."""

    instrument: str = Field(description="Name of the instrument to use")
    config: InstrumentConfig | None = Field(
        default=None,
        description="Optional configuration overrides for this step",
    )


class ArrangementProposal(BaseModel):
    """Proposed arrangement from the planner.

    Claude analyzes a task and proposes either a sequential or parallel
    composition of instruments. The proposal includes rationale and
    termination criteria.
    """

    type: Literal["sequential", "parallel", "single"] = Field(
        description="Composition type: sequential pipeline, parallel fan-out, or single instrument"
    )
    rationale: str = Field(
        description="Explanation of why this arrangement fits the task"
    )
    termination_criteria: str = Field(
        description="How we know when the task is complete"
    )

    # For sequential compositions
    steps: list[ArrangementStep] | None = Field(
        default=None,
        description="Ordered steps for sequential composition",
    )

    # For parallel compositions
    branches: list[str] | None = Field(
        default=None,
        description="Instrument names to run in parallel",
    )
    merge_instrument: str = Field(
        default="synthesis",
        description="Instrument to merge parallel results",
    )
    timeout_seconds: float | None = Field(
        default=None,
        description="Per-branch timeout for parallel execution",
    )

    # For single instrument
    instrument: str | None = Field(
        default=None,
        description="Instrument name for single-instrument execution",
    )


class ArrangementValidation(BaseModel):
    """Result of validating an arrangement proposal."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
