"""Knowledge sync models (Phase 5B).

Wire-transfer models for syncing knowledge between server and rooms,
plus room learning intake and aggregation.
"""

from datetime import datetime, UTC
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeSyncEntry(BaseModel):
    """Lightweight knowledge entry for wire transfer."""

    id: str
    category: str
    title: str
    content: str
    source: str
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)
    version: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeSyncPush(BaseModel):
    """Server-to-room knowledge push (delta since last sync)."""

    server_version: int
    entries: list[KnowledgeSyncEntry] = Field(default_factory=list)
    removed_ids: list[str] = Field(default_factory=list)


class KnowledgeSyncState(BaseModel):
    """Tracks per-room sync state."""

    room_id: str
    last_synced_version: int = 0
    last_sync_at: datetime | None = None


class RoomLearning(BaseModel):
    """A single observation/learning reported by a room."""

    category: str
    title: str
    content: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    room_id: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoomLearningBatch(BaseModel):
    """Batch of learnings from a room."""

    room_id: str
    learnings: list[RoomLearning]


class LearningAggregationResult(BaseModel):
    """Result of aggregating room learnings into knowledge entries."""

    entries_created: int = 0
    entries_updated: int = 0
    learnings_processed: int = 0
