"""Knowledge file models (Phase 5A).

Structured knowledge entries that capture what the system knows about
its capabilities, boundaries, patterns, changelog, and per-user learnings.
"""

from datetime import datetime, UTC
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class KnowledgeCategory(str, Enum):
    """Categories of knowledge files."""

    CAPABILITIES = "capabilities"
    BOUNDARIES = "boundaries"
    PATTERNS = "patterns"
    CHANGELOG = "changelog"
    USER = "user"


class KnowledgeSource(str, Enum):
    """Source of a knowledge entry."""

    SEED = "seed"
    ERROR_TRACKER = "error_tracker"
    ARRANGEMENT_TRACKER = "arrangement_tracker"
    TRUST_TRACKER = "trust_tracker"
    MANUAL = "manual"
    SYSTEM = "system"


# Display titles for each category
CATEGORY_TITLES: dict[KnowledgeCategory, str] = {
    KnowledgeCategory.CAPABILITIES: "Capabilities",
    KnowledgeCategory.BOUNDARIES: "Boundaries",
    KnowledgeCategory.PATTERNS: "Patterns",
    KnowledgeCategory.CHANGELOG: "Changelog",
    KnowledgeCategory.USER: "User Knowledge",
}


class KnowledgeEntry(BaseModel):
    """A single knowledge entry stored in the database."""

    id: UUID = Field(default_factory=uuid4)
    category: KnowledgeCategory
    title: str
    content: str
    source: KnowledgeSource = KnowledgeSource.SEED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    user_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeFile(BaseModel):
    """Rendered knowledge file — markdown + structured entries."""

    category: KnowledgeCategory
    title: str
    markdown: str
    entries: list[KnowledgeEntry]
    last_updated: datetime | None = None


class UserKnowledge(BaseModel):
    """Per-user knowledge aggregation."""

    user_id: str
    trust_level: int = 0
    total_tasks: int = 0
    success_rate: float = 0.0
    preferred_patterns: list[str] = Field(default_factory=list)
    entries: list[KnowledgeEntry] = Field(default_factory=list)
    markdown: str = ""


class KnowledgeEntryCreate(BaseModel):
    """Request model for creating a manual knowledge entry."""

    category: KnowledgeCategory
    title: str
    content: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    user_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class KnowledgeRefreshResult(BaseModel):
    """Result of a knowledge refresh operation."""

    entries_created: int = 0
    entries_updated: int = 0
    entries_removed: int = 0
    sources_refreshed: list[str] = Field(default_factory=list)
