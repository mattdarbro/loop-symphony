"""Dispatch communication models."""

from datetime import datetime, UTC
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    """Communication channel types."""
    DIRECT = "direct"        # 1:1 conductor-to-conductor
    BROADCAST = "broadcast"  # 1:many announcements
    REQUEST = "request"      # request-response pattern


class MessagePriority(str, Enum):
    """Message priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class DispatchMessage(BaseModel):
    """A message sent through the Dispatch system."""

    id: UUID = Field(default_factory=uuid4)
    channel: str                          # channel name/id
    channel_type: ChannelType = ChannelType.DIRECT
    sender_id: str                        # conductor or system id
    recipient_id: str | None = None       # None for broadcast
    payload: dict = Field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    correlation_id: UUID | None = None    # for request-response pairing
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: int = 300


class DispatchChannel(BaseModel):
    """A communication channel in the Dispatch system."""

    name: str
    channel_type: ChannelType = ChannelType.DIRECT
    participants: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = Field(default_factory=dict)
