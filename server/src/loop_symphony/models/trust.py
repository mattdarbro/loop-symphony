"""Trust escalation models (Phase 3D).

Tracks user/app success patterns and suggests trust level changes.
Trust levels:
  0 = Supervised: return plan for approval before executing
  1 = Semi-autonomous: auto-execute, return detailed results for review
  2 = Autonomous: full autonomy, only critical errors surface
"""

from datetime import datetime, UTC
from uuid import UUID

from pydantic import BaseModel, Field


class TrustMetrics(BaseModel):
    """Trust metrics for a user/app."""

    app_id: UUID
    user_id: UUID | None = None  # None = app-level metrics

    # Execution counts
    total_tasks: int = 0
    successful_tasks: int = 0  # outcome = complete or saturated
    failed_tasks: int = 0  # outcome = inconclusive or bounded
    consecutive_successes: int = 0

    # Current state
    current_trust_level: int = Field(default=0, ge=0, le=2)

    # Timestamps
    last_task_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def success_rate(self) -> float:
        """Calculate overall success rate."""
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / self.total_tasks

    @property
    def suggested_trust_level(self) -> int:
        """Suggest trust level based on success patterns.

        Rules:
        - Level 0 -> 1: 5+ consecutive successes, 80%+ success rate
        - Level 1 -> 2: 10+ consecutive successes, 90%+ success rate
        - Never auto-demote (user decision)
        """
        if self.current_trust_level == 0:
            if self.consecutive_successes >= 5 and self.success_rate >= 0.8:
                return 1
        elif self.current_trust_level == 1:
            if self.consecutive_successes >= 10 and self.success_rate >= 0.9:
                return 2
        return self.current_trust_level

    @property
    def should_suggest_upgrade(self) -> bool:
        """Whether we should suggest upgrading trust level."""
        return self.suggested_trust_level > self.current_trust_level


class TrustSuggestion(BaseModel):
    """Suggestion to upgrade trust level."""

    current_level: int
    suggested_level: int
    reason: str
    metrics: TrustMetrics


class TrustLevelUpdate(BaseModel):
    """Request to update trust level."""

    trust_level: int = Field(ge=0, le=2)
