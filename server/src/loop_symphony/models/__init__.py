"""Pydantic models for Loop Symphony - the contracts."""

from loop_symphony.models.arrangement import (
    ArrangementProposal,
    ArrangementStep,
    ArrangementValidation,
)
from loop_symphony.models.finding import ExecutionMetadata, Finding, Source
from loop_symphony.models.loop_proposal import (
    LoopExecutionPlan,
    LoopPhase,
    LoopProposal,
    LoopProposalValidation,
)
from loop_symphony.models.saved_arrangement import (
    ArrangementExecution,
    ArrangementStats,
    ArrangementSuggestion,
    SaveArrangementRequest,
    SavedArrangement,
)
from loop_symphony.models.heartbeat import (
    Heartbeat,
    HeartbeatCreate,
    HeartbeatRun,
    HeartbeatStatus,
    HeartbeatUpdate,
)
from loop_symphony.models.error_learning import (
    ErrorCategory,
    ErrorPattern,
    ErrorRecord,
    ErrorSeverity,
    ErrorStats,
    LearningInsight,
    RecordErrorRequest,
)
from loop_symphony.models.health import ComponentHealth, HealthStatus, SystemHealth
from loop_symphony.models.notification import (
    ChannelConfig,
    Notification,
    NotificationChannel,
    NotificationHistory,
    NotificationPreferences,
    NotificationPriority,
    NotificationResult,
    NotificationType,
    SendNotificationRequest,
)
from loop_symphony.models.identity import App, AuthContext, UserProfile
from loop_symphony.models.intent import (
    Intent,
    IntentType,
    UrgencyLevel,
    infer_intent,
)
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.trust import TrustLevelUpdate, TrustMetrics, TrustSuggestion
from loop_symphony.models.task import (
    TaskContext,
    TaskPendingResponse,
    TaskPlan,
    TaskPreferences,
    TaskRequest,
    TaskResponse,
    TaskSubmitResponse,
)

__all__ = [
    "App",
    "ArrangementExecution",
    "ComponentHealth",
    "ArrangementProposal",
    "ArrangementStats",
    "ArrangementStep",
    "ArrangementSuggestion",
    "ArrangementValidation",
    "AuthContext",
    "ErrorCategory",
    "ErrorPattern",
    "ErrorRecord",
    "ErrorSeverity",
    "ErrorStats",
    "ExecutionMetadata",
    "Finding",
    "Heartbeat",
    "HeartbeatCreate",
    "HeartbeatRun",
    "HeartbeatStatus",
    "HeartbeatUpdate",
    "HealthStatus",
    "infer_intent",
    "Intent",
    "IntentType",
    "LearningInsight",
    "LoopExecutionPlan",
    "ChannelConfig",
    "Notification",
    "NotificationChannel",
    "NotificationHistory",
    "NotificationPreferences",
    "NotificationPriority",
    "NotificationResult",
    "NotificationType",
    "SendNotificationRequest",
    "LoopPhase",
    "LoopProposal",
    "LoopProposalValidation",
    "Outcome",
    "RecordErrorRequest",
    "SaveArrangementRequest",
    "SavedArrangement",
    "Source",
    "SystemHealth",
    "TaskContext",
    "TaskPendingResponse",
    "TaskPlan",
    "TaskPreferences",
    "TaskRequest",
    "TaskResponse",
    "TaskSubmitResponse",
    "TrustLevelUpdate",
    "TrustMetrics",
    "TrustSuggestion",
    "UrgencyLevel",
    "UserProfile",
]
