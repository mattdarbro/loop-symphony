"""Magenta Loop models — content analytics pipeline types."""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DiagnosisType(str, Enum):
    """Types of content performance diagnoses."""

    WEAK_HOOK = "weak_hook"
    RETENTION_DROP = "retention_drop"
    THUMBNAIL_UNDERPERFORMANCE = "thumbnail_underperformance"
    POSTING_TIME_WRONG = "posting_time_wrong"
    SUBSCRIBER_ONLY = "subscriber_only"
    AUDIENCE_MISMATCH = "audience_mismatch"
    STRONG_PERFORMANCE = "strong_performance"


class PrescriptionStatus(str, Enum):
    """Lifecycle status of a prescription."""

    PENDING = "pending"
    APPLIED = "applied"
    EVALUATED = "evaluated"
    SKIPPED = "skipped"


class ContentMetrics(BaseModel):
    """Raw analytics data for a piece of content."""

    content_id: str
    creator_id: str
    platform: str = "youtube"
    title: str | None = None
    published_at: datetime | None = None

    # Core metrics
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    subscribers_gained: int = 0
    subscribers_lost: int = 0

    # Retention
    avg_view_duration_seconds: float = 0.0
    avg_view_percentage: float = 0.0
    retention_curve: list[float] = Field(default_factory=list)
    total_duration_seconds: float = 0.0

    # Traffic sources (percentages)
    traffic_sources: dict[str, float] = Field(default_factory=dict)

    # Demographics
    demographics: dict[str, dict] = Field(default_factory=dict)

    # Channel context
    subscriber_count: int = 0
    category: str | None = None

    # Impressions
    impressions: int = 0
    impression_click_through_rate: float = 0.0


class Diagnosis(BaseModel):
    """A single diagnostic finding about content performance."""

    id: UUID = Field(default_factory=uuid4)
    diagnosis_type: DiagnosisType
    severity: str = "medium"  # low, medium, high
    title: str
    description: str
    evidence: str = ""
    metric_value: float | None = None
    benchmark_value: float | None = None


class Prescription(BaseModel):
    """An actionable recommendation based on a diagnosis."""

    id: UUID = Field(default_factory=uuid4)
    app_id: str | None = None
    creator_id: str
    content_id: str
    diagnosis_type: DiagnosisType
    title: str
    description: str
    specific_action: str
    reference_content_id: str | None = None
    status: PrescriptionStatus = PrescriptionStatus.PENDING
    followup_content_id: str | None = None
    effectiveness_score: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TrackingResult(BaseModel):
    """Result of evaluating a past prescription's effectiveness."""

    prescription_id: UUID
    original_content_id: str
    followup_content_id: str
    metric_improvement: dict[str, float] = Field(default_factory=dict)
    effectiveness_score: float = 0.0
    summary: str = ""
    learned_pattern: str | None = None


class MagentaReport(BaseModel):
    """Generated narrative report from the Magenta Loop."""

    id: UUID = Field(default_factory=uuid4)
    app_id: str | None = None
    creator_id: str
    report_type: str = "standard"  # standard, weekly, urgent
    title: str
    narrative: str
    diagnoses_count: int = 0
    prescriptions_count: int = 0
    tracking_summary: str | None = None
    notification_payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
