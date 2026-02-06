"""Heartbeat models for scheduled recurring tasks."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class HeartbeatStatus(str, Enum):
    """Status of a heartbeat run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Heartbeat(BaseModel):
    """Recurring task definition."""

    id: UUID
    app_id: UUID
    user_id: UUID | None = None  # NULL = app-wide heartbeat
    name: str
    query_template: str
    cron_expression: str
    timezone: str = "UTC"
    is_active: bool = True
    context_template: dict = Field(default_factory=dict)
    webhook_url: str | None = None  # URL to POST results to on completion
    created_at: datetime
    updated_at: datetime


class HeartbeatCreate(BaseModel):
    """Request to create a heartbeat."""

    name: str
    query_template: str
    cron_expression: str
    timezone: str = "UTC"
    context_template: dict = Field(default_factory=dict)
    webhook_url: str | None = None  # URL to POST results to on completion


class HeartbeatUpdate(BaseModel):
    """Request to update a heartbeat."""

    name: str | None = None
    query_template: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    is_active: bool | None = None
    context_template: dict | None = None
    webhook_url: str | None = None  # URL to POST results to on completion


class HeartbeatRun(BaseModel):
    """Single execution of a heartbeat."""

    id: UUID
    heartbeat_id: UUID
    task_id: UUID | None = None
    status: HeartbeatStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
