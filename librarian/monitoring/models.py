"""Monitoring models — error learning and intervention (combined).

Error learning models (Phase 3H):
Tracks errors with context, detects patterns, and suggests adjustments
to avoid repeating mistakes.

Intervention models (Phase 5C):
Four intervention types:
- Proactive suggestions: detect recurring pain points
- Pushback: redirect unrealistic requests
- Scoping: break down overwhelming requests
- Education: gentle capability discovery
"""

from datetime import datetime, UTC
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Error learning models
# ---------------------------------------------------------------------------

class ErrorCategory(str, Enum):
    """Classification of error types."""

    # External service failures
    API_FAILURE = "api_failure"          # External API returned error
    TIMEOUT = "timeout"                   # Operation timed out
    RATE_LIMITED = "rate_limited"         # Hit rate limits

    # Content/quality issues
    LOW_CONFIDENCE = "low_confidence"     # Couldn't reach confidence threshold
    CONTRADICTIONS = "contradictions"     # Found irreconcilable contradictions
    NO_RESULTS = "no_results"             # Search/research yielded nothing

    # Validation/constraint issues
    VALIDATION = "validation"             # Input validation failed
    DEPTH_EXCEEDED = "depth_exceeded"     # Hit max recursion depth
    CONTEXT_OVERFLOW = "context_overflow" # Context too large

    # Execution issues
    INSTRUMENT_FAILURE = "instrument_failure"  # Instrument threw exception
    ARRANGEMENT_FAILURE = "arrangement_failure"  # Composition failed
    TOOL_FAILURE = "tool_failure"         # Underlying tool failed

    # Unknown
    UNKNOWN = "unknown"


class ErrorSeverity(str, Enum):
    """How severe was the error?"""

    LOW = "low"           # Recoverable, minor impact
    MEDIUM = "medium"     # Affected result quality
    HIGH = "high"         # Task failed completely
    CRITICAL = "critical" # System-level issue


class ErrorRecord(BaseModel):
    """A recorded error with learning context."""

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Classification
    category: ErrorCategory
    severity: ErrorSeverity = ErrorSeverity.MEDIUM

    # Context - what was happening when error occurred
    task_id: str | None = None
    query: str | None = None
    instrument: str | None = None
    arrangement_type: str | None = None  # sequential, parallel, novel
    tool: str | None = None

    # Error details
    error_message: str
    error_type: str | None = None  # Exception class name
    stack_trace: str | None = None

    # Learning context
    query_intent: str | None = None  # From intent taxonomy
    iteration: int | None = None     # Which iteration failed
    findings_count: int | None = None  # How many findings before failure

    # Resolution
    was_recovered: bool = False      # Did we recover and complete?
    recovery_method: str | None = None  # How we recovered


class ErrorPattern(BaseModel):
    """A detected pattern across multiple errors."""

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Pattern identification
    name: str  # e.g., "tavily_rate_limits_morning"
    description: str

    # Pattern criteria
    category: ErrorCategory
    instrument: str | None = None   # If pattern is instrument-specific
    tool: str | None = None         # If pattern is tool-specific
    query_pattern: str | None = None  # Regex or keywords that trigger

    # Statistics
    occurrence_count: int = 0
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Learning
    suggested_action: str | None = None  # What to do differently
    success_after_adjustment: int = 0    # Times adjustment worked
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class LearningInsight(BaseModel):
    """A suggestion based on learned patterns."""

    pattern_id: UUID
    pattern_name: str
    suggestion: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str  # Why this suggestion is relevant


class ErrorStats(BaseModel):
    """Aggregate error statistics."""

    total_errors: int = 0
    errors_by_category: dict[str, int] = Field(default_factory=dict)
    errors_by_severity: dict[str, int] = Field(default_factory=dict)
    errors_by_instrument: dict[str, int] = Field(default_factory=dict)
    recovery_rate: float = 0.0  # Percentage of recovered errors
    patterns_detected: int = 0

    # Time-based
    errors_last_hour: int = 0
    errors_last_24h: int = 0


class RecordErrorRequest(BaseModel):
    """Request to record an error."""

    category: ErrorCategory
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    error_message: str
    task_id: str | None = None
    query: str | None = None
    instrument: str | None = None
    tool: str | None = None
    error_type: str | None = None
    was_recovered: bool = False
    recovery_method: str | None = None


# ---------------------------------------------------------------------------
# Intervention models
# ---------------------------------------------------------------------------

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
