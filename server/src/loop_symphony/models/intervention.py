"""Intervention models for post-task enrichment (Phase 5C).

Four intervention types:
- Proactive suggestions: detect recurring pain points
- Pushback: redirect unrealistic requests
- Scoping: break down overwhelming requests
- Education: gentle capability discovery
"""

from enum import Enum

from pydantic import BaseModel, Field


class InterventionType(str, Enum):
    """Types of post-task interventions."""

    PROACTIVE = "proactive"
    PUSHBACK = "pushback"
    SCOPING = "scoping"
    EDUCATION = "education"


class Intervention(BaseModel):
    """A single intervention suggestion."""

    type: InterventionType
    message: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = ""  # What triggered it, e.g. "error_pattern:timeout"


class InterventionContext(BaseModel):
    """Assembled context for detector functions to evaluate."""

    query: str
    response_summary: str
    response_outcome: str  # Outcome enum value as string
    response_confidence: float
    instrument_used: str
    intent_type: str | None = None
    trust_level: int = 0
    error_patterns: list[dict] = Field(default_factory=list)
    recent_queries: list[str] = Field(default_factory=list)
    available_instruments: list[str] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)


class InterventionResult(BaseModel):
    """Result of running all detectors on a task response."""

    interventions: list[Intervention] = Field(default_factory=list)
    context_used: InterventionContext | None = None
