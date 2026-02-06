"""Trust escalation tracker (Phase 3D).

Tracks user/app success patterns and manages trust level suggestions.
"""

from datetime import datetime, UTC
from uuid import UUID

from loop_symphony.models.outcome import Outcome
from loop_symphony.models.trust import TrustMetrics, TrustSuggestion


class TrustTracker:
    """Tracks trust metrics per user/app.

    Provides:
    - Record task outcomes to update metrics
    - Get current trust metrics
    - Get trust upgrade suggestions
    - Update trust level
    """

    def __init__(self) -> None:
        # In-memory storage: (app_id, user_id) -> TrustMetrics
        # user_id can be None for app-level metrics
        self._metrics: dict[tuple[UUID, UUID | None], TrustMetrics] = {}

    def _get_key(
        self, app_id: UUID, user_id: UUID | None = None
    ) -> tuple[UUID, UUID | None]:
        """Get storage key for metrics."""
        return (app_id, user_id)

    def get_metrics(
        self, app_id: UUID, user_id: UUID | None = None
    ) -> TrustMetrics:
        """Get trust metrics for a user/app.

        Creates new metrics if none exist.

        Args:
            app_id: The application ID
            user_id: Optional user ID (None for app-level)

        Returns:
            TrustMetrics for the user/app
        """
        key = self._get_key(app_id, user_id)
        if key not in self._metrics:
            self._metrics[key] = TrustMetrics(app_id=app_id, user_id=user_id)
        return self._metrics[key]

    def record_outcome(
        self,
        app_id: UUID,
        outcome: Outcome,
        user_id: UUID | None = None,
    ) -> TrustMetrics:
        """Record a task outcome to update trust metrics.

        Args:
            app_id: The application ID
            outcome: The task outcome
            user_id: Optional user ID

        Returns:
            Updated TrustMetrics
        """
        metrics = self.get_metrics(app_id, user_id)

        # Update counts
        metrics.total_tasks += 1

        # Determine success/failure
        is_success = outcome in (Outcome.COMPLETE, Outcome.SATURATED)

        if is_success:
            metrics.successful_tasks += 1
            metrics.consecutive_successes += 1
        else:
            metrics.failed_tasks += 1
            metrics.consecutive_successes = 0  # Reset on failure

        # Update timestamps
        metrics.last_task_at = datetime.now(UTC)
        metrics.updated_at = datetime.now(UTC)

        return metrics

    def get_suggestion(
        self, app_id: UUID, user_id: UUID | None = None
    ) -> TrustSuggestion | None:
        """Get trust upgrade suggestion if warranted.

        Args:
            app_id: The application ID
            user_id: Optional user ID

        Returns:
            TrustSuggestion if upgrade is suggested, None otherwise
        """
        metrics = self.get_metrics(app_id, user_id)

        if not metrics.should_suggest_upgrade:
            return None

        current = metrics.current_trust_level
        suggested = metrics.suggested_trust_level

        if suggested == 1:
            reason = (
                f"You've had {metrics.consecutive_successes} consecutive successful "
                f"tasks with a {metrics.success_rate:.0%} overall success rate. "
                "Consider enabling semi-autonomous mode for faster execution."
            )
        else:  # suggested == 2
            reason = (
                f"Excellent track record with {metrics.consecutive_successes} "
                f"consecutive successes and {metrics.success_rate:.0%} success rate. "
                "You may want to enable full autonomous mode."
            )

        return TrustSuggestion(
            current_level=current,
            suggested_level=suggested,
            reason=reason,
            metrics=metrics,
        )

    def update_trust_level(
        self, app_id: UUID, trust_level: int, user_id: UUID | None = None
    ) -> TrustMetrics:
        """Update the trust level for a user/app.

        Args:
            app_id: The application ID
            trust_level: New trust level (0-2)
            user_id: Optional user ID

        Returns:
            Updated TrustMetrics

        Raises:
            ValueError: If trust_level is invalid
        """
        if not 0 <= trust_level <= 2:
            raise ValueError("trust_level must be 0, 1, or 2")

        metrics = self.get_metrics(app_id, user_id)
        metrics.current_trust_level = trust_level
        metrics.updated_at = datetime.now(UTC)

        return metrics

    def reset_metrics(
        self, app_id: UUID, user_id: UUID | None = None
    ) -> None:
        """Reset metrics for a user/app.

        Args:
            app_id: The application ID
            user_id: Optional user ID
        """
        key = self._get_key(app_id, user_id)
        if key in self._metrics:
            del self._metrics[key]
