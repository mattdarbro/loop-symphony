"""Finding and Source models."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from loop_library.models.process import ProcessType


class Source(BaseModel):
    """A source of information."""

    url: str | None = None
    title: str | None = None
    snippet: str | None = None


class Finding(BaseModel):
    """A single finding from research."""

    content: str
    source: str | None = None
    confidence: float = 1.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExecutionMetadata(BaseModel):
    """Metadata about task execution."""

    instrument_used: str
    iterations: int
    duration_ms: int
    sources_consulted: list[str] = Field(default_factory=list)
    process_type: ProcessType = ProcessType.AUTONOMIC
    room_id: str | None = None
    failover_events: list[dict] = Field(default_factory=list)
