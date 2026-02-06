"""Models for meta-learning / saved arrangements (Phase 3C).

Tracks successful arrangements and allows them to be saved as
named compositions for future reuse.
"""

from datetime import datetime, UTC
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from loop_symphony.models.arrangement import ArrangementProposal
from loop_symphony.models.loop_proposal import LoopProposal


class ArrangementExecution(BaseModel):
    """Record of a single arrangement execution."""

    arrangement_id: str
    task_id: str
    outcome: str  # complete, saturated, bounded, inconclusive
    confidence: float
    duration_ms: int
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArrangementStats(BaseModel):
    """Aggregated statistics for an arrangement."""

    total_executions: int = 0
    successful_executions: int = 0  # outcome = complete
    average_confidence: float = 0.0
    average_duration_ms: float = 0.0
    last_executed_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions


class SavedArrangement(BaseModel):
    """A saved arrangement for reuse.

    Can be either an ArrangementProposal (composition of instruments)
    or a LoopProposal (custom loop with phases).
    """

    id: UUID
    app_id: UUID | None = None  # NULL = global, otherwise app-specific
    name: str = Field(description="Unique name for this arrangement")
    description: str = Field(description="What this arrangement is good for")
    arrangement_type: Literal["composition", "loop"]

    # The actual arrangement spec (one of these will be set)
    composition_spec: ArrangementProposal | None = None
    loop_spec: LoopProposal | None = None

    # Metadata
    query_patterns: list[str] = Field(
        default_factory=list,
        description="Query patterns this arrangement works well for",
    )
    tags: list[str] = Field(default_factory=list)

    # Statistics
    stats: ArrangementStats = Field(default_factory=ArrangementStats)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Status
    is_active: bool = True


class SaveArrangementRequest(BaseModel):
    """Request to save an arrangement."""

    name: str
    description: str
    query_patterns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # One of these must be provided
    composition_spec: ArrangementProposal | None = None
    loop_spec: LoopProposal | None = None


class ArrangementSuggestion(BaseModel):
    """Suggestion to save a high-performing arrangement."""

    arrangement_type: Literal["composition", "loop"]
    composition_spec: ArrangementProposal | None = None
    loop_spec: LoopProposal | None = None

    # Why we're suggesting this
    reason: str
    confidence: float
    success_rate: float
    execution_count: int

    # Suggested metadata
    suggested_name: str
    suggested_description: str
    suggested_patterns: list[str] = Field(default_factory=list)
