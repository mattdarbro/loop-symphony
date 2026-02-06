"""Models for loop proposal system (Phase 3B).

Level 5 creativity: Propose entirely new loop specs when existing
instruments don't fit. Unlike 3A (composing existing instruments),
this defines new behavior patterns with custom phases.
"""

from typing import Literal

from pydantic import BaseModel, Field


class LoopPhase(BaseModel):
    """A phase in a proposed loop.

    Each phase can either use an existing instrument or define
    custom behavior via a prompt template.
    """

    name: str = Field(description="Phase name (e.g., 'hypothesize', 'gather')")
    description: str = Field(description="What this phase accomplishes")
    action: Literal["instrument", "prompt", "spawn"] = Field(
        default="prompt",
        description="How to execute: use instrument, custom prompt, or spawn sub-task",
    )
    instrument: str | None = Field(
        default=None,
        description="Instrument to use (if action='instrument')",
    )
    prompt_template: str | None = Field(
        default=None,
        description="Custom prompt template (if action='prompt'). "
        "Can use {query}, {previous_findings}, {phase_name}",
    )
    max_iterations: int = Field(
        default=1,
        description="Max iterations for this phase",
    )


class LoopProposal(BaseModel):
    """Proposal for a new loop type.

    Defines a complete loop specification including phases,
    termination criteria, and required capabilities. Must follow
    scientific method structure.
    """

    name: str = Field(description="Loop name (e.g., 'fact_check', 'deep_dive')")
    description: str = Field(description="What this loop type is designed for")
    phases: list[LoopPhase] = Field(
        description="Ordered phases of the loop",
        min_length=2,  # Must have at least 2 phases
    )
    termination_criteria: str = Field(
        description="How to determine when the loop is complete",
    )
    max_total_iterations: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum total iterations across all phases",
    )
    required_capabilities: list[str] = Field(
        default_factory=lambda: ["reasoning"],
        description="Capabilities needed to execute this loop",
    )
    scientific_method_phases: list[str] = Field(
        default_factory=lambda: ["hypothesize", "gather", "analyze", "synthesize"],
        description="Which scientific method phases are covered",
    )


class LoopProposalValidation(BaseModel):
    """Result of validating a loop proposal."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scientific_method_coverage: dict[str, bool] = Field(
        default_factory=dict,
        description="Which scientific method phases are covered",
    )


class LoopExecutionPlan(BaseModel):
    """Execution plan for an approved loop proposal.

    Returned when trust_level=0 for user approval.
    """

    proposal: LoopProposal
    validation: LoopProposalValidation
    estimated_iterations: int
    estimated_duration_seconds: int
    requires_approval: bool = True
