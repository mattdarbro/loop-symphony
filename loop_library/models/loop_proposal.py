"""Models for loop proposal system (Phase 3B)."""

from typing import Literal

from pydantic import BaseModel, Field


class LoopPhase(BaseModel):
    """A phase in a proposed loop."""

    name: str = Field(description="Phase name (e.g., 'hypothesize', 'gather')")
    description: str = Field(description="What this phase accomplishes")
    action: Literal["instrument", "prompt", "spawn"] = Field(
        default="prompt",
        description="How to execute: use instrument, custom prompt, or spawn sub-task",
    )
    instrument: str | None = Field(default=None)
    prompt_template: str | None = Field(default=None)
    max_iterations: int = Field(default=1)


class LoopProposal(BaseModel):
    """Proposal for a new loop type."""

    name: str = Field(description="Loop name (e.g., 'fact_check', 'deep_dive')")
    description: str = Field(description="What this loop type is designed for")
    phases: list[LoopPhase] = Field(min_length=2)
    termination_criteria: str = Field(
        description="How to determine when the loop is complete",
    )
    max_total_iterations: int = Field(default=10, ge=1, le=20)
    required_capabilities: list[str] = Field(
        default_factory=lambda: ["reasoning"],
    )
    scientific_method_phases: list[str] = Field(
        default_factory=lambda: ["hypothesize", "gather", "analyze", "synthesize"],
    )


class LoopProposalValidation(BaseModel):
    """Result of validating a loop proposal."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scientific_method_coverage: dict[str, bool] = Field(default_factory=dict)


class LoopExecutionPlan(BaseModel):
    """Execution plan for an approved loop proposal."""

    proposal: LoopProposal
    validation: LoopProposalValidation
    estimated_iterations: int
    estimated_duration_seconds: int
    requires_approval: bool = True
