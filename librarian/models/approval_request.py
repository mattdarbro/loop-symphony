"""Approval request model for governance flow."""

from datetime import datetime, UTC
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    """A request for human approval before execution."""

    id: UUID = Field(default_factory=uuid4)
    conductor_id: str
    action_type: str  # e.g. "execute_arrangement", "trust_upgrade", "financial_data"
    description: str
    context: dict = Field(default_factory=dict)
    trust_level: int = 0
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    ttl_seconds: int = 300  # 5 minute default expiry
