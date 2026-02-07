"""Notification models (Phase 3I).

Supports multiple notification channels for task completion alerts,
heartbeat results, and system notifications.
"""

from datetime import datetime, UTC
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class NotificationChannel(str, Enum):
    """Available notification channels."""

    TELEGRAM = "telegram"    # Telegram Bot API
    WEBHOOK = "webhook"      # Generic HTTP webhook
    PUSH = "push"            # iOS push notification (via APNs)
    EMAIL = "email"          # Email (future)


class NotificationPriority(str, Enum):
    """Notification priority levels."""

    LOW = "low"          # Can be batched/delayed
    NORMAL = "normal"    # Send promptly
    HIGH = "high"        # Send immediately
    CRITICAL = "critical"  # Wake device, bypass DND


class NotificationType(str, Enum):
    """Types of notifications."""

    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"
    HEARTBEAT_RESULT = "heartbeat_result"
    SYSTEM_ALERT = "system_alert"
    TRUST_ESCALATION = "trust_escalation"


class ChannelConfig(BaseModel):
    """Configuration for a notification channel."""

    channel: NotificationChannel
    enabled: bool = True

    # Channel-specific settings
    telegram_chat_id: str | None = None
    webhook_url: str | None = None
    push_device_token: str | None = None
    email_address: str | None = None

    # Preferences
    min_priority: NotificationPriority = NotificationPriority.NORMAL
    quiet_hours_start: int | None = None  # Hour (0-23) to start quiet hours
    quiet_hours_end: int | None = None    # Hour (0-23) to end quiet hours


class NotificationPreferences(BaseModel):
    """Per-user notification preferences."""

    user_id: UUID
    app_id: UUID

    # Which channels are configured
    channels: list[ChannelConfig] = Field(default_factory=list)

    # Global preferences
    enabled: bool = True
    notify_on_complete: bool = True
    notify_on_failure: bool = True
    notify_on_heartbeat: bool = True

    # Batching
    batch_low_priority: bool = True  # Batch low-priority into digest
    batch_interval_minutes: int = 30  # How often to send digest

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Notification(BaseModel):
    """A notification to be sent."""

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Target
    user_id: UUID | None = None
    app_id: UUID | None = None

    # Content
    type: NotificationType
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL

    # Context
    task_id: str | None = None
    data: dict = Field(default_factory=dict)  # Additional payload

    # Delivery
    channels: list[NotificationChannel] = Field(default_factory=list)


class NotificationResult(BaseModel):
    """Result of sending a notification."""

    notification_id: UUID
    channel: NotificationChannel
    success: bool
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None
    external_id: str | None = None  # Message ID from external service


class NotificationHistory(BaseModel):
    """Record of a sent notification."""

    id: UUID = Field(default_factory=uuid4)
    notification_id: UUID
    user_id: UUID | None = None
    app_id: UUID | None = None

    type: NotificationType
    title: str
    body: str

    results: list[NotificationResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SendNotificationRequest(BaseModel):
    """Request to send a notification."""

    type: NotificationType
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    task_id: str | None = None
    data: dict = Field(default_factory=dict)
    channels: list[NotificationChannel] | None = None  # None = use preferences
