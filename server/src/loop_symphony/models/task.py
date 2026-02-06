"""Task request and response models."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from loop_symphony.models.finding import ExecutionMetadata, Finding
from loop_symphony.models.outcome import Outcome, TaskStatus


class TaskContext(BaseModel):
    """Context provided with a task request."""

    user_id: str | None = None
    conversation_summary: str | None = None
    attachments: list[str] = Field(default_factory=list)
    location: str | None = None
    input_results: list[dict] | None = None
    checkpoint_fn: Any = Field(default=None, exclude=True)
    spawn_fn: Any = Field(default=None, exclude=True)
    depth: int = 0
    max_depth: int = 3
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskPreferences(BaseModel):
    """User preferences for task execution."""

    thoroughness: Literal["quick", "balanced", "thorough"] = "balanced"
    trust_level: int = Field(default=0, ge=0, le=2)  # 0=supervised, 1=semi, 2=auto
    notify_on_complete: bool = True
    max_spawn_depth: int | None = None


class TaskRequest(BaseModel):
    """Request from iOS app to server."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    query: str
    context: TaskContext | None = None
    preferences: TaskPreferences | None = None


class TaskPlan(BaseModel):
    """Execution plan for a task (returned when trust_level=0)."""

    task_id: str
    query: str
    instrument: str
    process_type: str
    estimated_iterations: int
    description: str
    requires_approval: bool = True


class TaskSubmitResponse(BaseModel):
    """Immediate response after submitting a task."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    message: str = "Task submitted successfully"
    plan: TaskPlan | None = None  # Included when trust_level=0


class TaskPendingResponse(BaseModel):
    """Response when task is still in progress."""

    task_id: str
    status: TaskStatus
    progress: str | None = None
    started_at: datetime | None = None


class TaskResponse(BaseModel):
    """Full response when task is complete."""

    request_id: str
    outcome: Outcome
    findings: list[Finding]
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: ExecutionMetadata
    discrepancy: str | None = None
    suggested_followups: list[str] = Field(default_factory=list)
