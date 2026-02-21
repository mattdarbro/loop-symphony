"""Trust escalation tracker."""

from datetime import datetime, UTC
from uuid import UUID

from loop_library.models.outcome import Outcome
from librarian.governance.models import TrustMetrics, TrustSuggestion


class TrustTracker:
    """Tracks trust metrics per user/app."""

    def __init__(self) -> None:
        self._metrics: dict[tuple[UUID, UUID | None], TrustMetrics] = {}

    def _get_key(self, app_id: UUID, user_id: UUID | None = None) -> tuple[UUID, UUID | None]:
        return (app_id, user_id)

    def get_metrics(self, app_id: UUID, user_id: UUID | None = None) -> TrustMetrics:
        key = self._get_key(app_id, user_id)
        if key not in self._metrics:
            self._metrics[key] = TrustMetrics(app_id=app_id, user_id=user_id)
        return self._metrics[key]

    def record_outcome(
        self, app_id: UUID, outcome: Outcome, user_id: UUID | None = None,
    ) -> TrustMetrics:
        metrics = self.get_metrics(app_id, user_id)
        metrics.total_tasks += 1
        is_success = outcome in (Outcome.COMPLETE, Outcome.SATURATED)
        if is_success:
            metrics.successful_tasks += 1
            metrics.consecutive_successes += 1
        else:
            metrics.failed_tasks += 1
            metrics.consecutive_successes = 0
        metrics.last_task_at = datetime.now(UTC)
        metrics.updated_at = datetime.now(UTC)
        return metrics

    def get_suggestion(
        self, app_id: UUID, user_id: UUID | None = None,
    ) -> TrustSuggestion | None:
        metrics = self.get_metrics(app_id, user_id)
        if not metrics.should_suggest_upgrade:
            return None

        current = metrics.current_trust_level
        suggested = metrics.suggested_trust_level

        reasons = {
            1: (
                f"You've had {metrics.consecutive_successes} consecutive successful "
                f"tasks with a {metrics.success_rate:.0%} overall success rate. "
                "Consider enabling semi-autonomous mode for faster execution."
            ),
            2: (
                f"Excellent track record with {metrics.consecutive_successes} "
                f"consecutive successes and {metrics.success_rate:.0%} success rate. "
                "You may want to enable full autonomous mode."
            ),
            3: (
                f"Outstanding track record with {metrics.consecutive_successes} "
                f"consecutive successes and {metrics.success_rate:.0%} success rate. "
                "Consider enabling delegating mode for sub-conductor management."
            ),
        }

        return TrustSuggestion(
            current_level=current,
            suggested_level=suggested,
            reason=reasons.get(suggested, "Trust upgrade suggested."),
            metrics=metrics,
        )

    def update_trust_level(
        self, app_id: UUID, trust_level: int, user_id: UUID | None = None,
    ) -> TrustMetrics:
        if not 0 <= trust_level <= 3:
            raise ValueError("trust_level must be 0, 1, 2, or 3")
        metrics = self.get_metrics(app_id, user_id)
        metrics.current_trust_level = trust_level
        metrics.updated_at = datetime.now(UTC)
        return metrics

    def reset_metrics(self, app_id: UUID, user_id: UUID | None = None) -> None:
        key = self._get_key(app_id, user_id)
        if key in self._metrics:
            del self._metrics[key]
