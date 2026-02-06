"""Tests for trust escalation system (Phase 3D)."""

import pytest
from uuid import uuid4

from loop_symphony.manager.trust_tracker import TrustTracker
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.trust import TrustLevelUpdate, TrustMetrics, TrustSuggestion


class TestTrustMetricsModel:
    """Tests for TrustMetrics model."""

    def test_default_values(self):
        metrics = TrustMetrics(app_id=uuid4())
        assert metrics.total_tasks == 0
        assert metrics.successful_tasks == 0
        assert metrics.failed_tasks == 0
        assert metrics.consecutive_successes == 0
        assert metrics.current_trust_level == 0

    def test_success_rate_empty(self):
        metrics = TrustMetrics(app_id=uuid4())
        assert metrics.success_rate == 0.0

    def test_success_rate_calculation(self):
        metrics = TrustMetrics(
            app_id=uuid4(),
            total_tasks=10,
            successful_tasks=8,
        )
        assert metrics.success_rate == 0.8

    def test_suggested_level_no_upgrade(self):
        metrics = TrustMetrics(
            app_id=uuid4(),
            total_tasks=3,
            successful_tasks=3,
            consecutive_successes=3,
            current_trust_level=0,
        )
        # Not enough consecutive successes (need 5)
        assert metrics.suggested_trust_level == 0
        assert not metrics.should_suggest_upgrade

    def test_suggested_level_0_to_1(self):
        metrics = TrustMetrics(
            app_id=uuid4(),
            total_tasks=10,
            successful_tasks=8,  # 80% success rate
            consecutive_successes=5,
            current_trust_level=0,
        )
        assert metrics.suggested_trust_level == 1
        assert metrics.should_suggest_upgrade

    def test_suggested_level_1_to_2(self):
        metrics = TrustMetrics(
            app_id=uuid4(),
            total_tasks=20,
            successful_tasks=18,  # 90% success rate
            consecutive_successes=10,
            current_trust_level=1,
        )
        assert metrics.suggested_trust_level == 2
        assert metrics.should_suggest_upgrade

    def test_no_auto_demote(self):
        # Even with low success rate, we don't auto-demote
        metrics = TrustMetrics(
            app_id=uuid4(),
            total_tasks=10,
            successful_tasks=3,  # 30% success rate
            consecutive_successes=0,
            current_trust_level=2,
        )
        assert metrics.suggested_trust_level == 2
        assert not metrics.should_suggest_upgrade


class TestTrustTrackerBasics:
    """Tests for TrustTracker basic operations."""

    def test_get_metrics_creates_new(self):
        tracker = TrustTracker()
        app_id = uuid4()

        metrics = tracker.get_metrics(app_id)
        assert metrics.app_id == app_id
        assert metrics.total_tasks == 0

    def test_get_metrics_same_instance(self):
        tracker = TrustTracker()
        app_id = uuid4()

        metrics1 = tracker.get_metrics(app_id)
        metrics2 = tracker.get_metrics(app_id)
        assert metrics1 is metrics2

    def test_get_metrics_per_user(self):
        tracker = TrustTracker()
        app_id = uuid4()
        user1 = uuid4()
        user2 = uuid4()

        metrics1 = tracker.get_metrics(app_id, user1)
        metrics2 = tracker.get_metrics(app_id, user2)

        assert metrics1 is not metrics2
        assert metrics1.user_id == user1
        assert metrics2.user_id == user2


class TestTrustTrackerRecording:
    """Tests for TrustTracker outcome recording."""

    def test_record_success(self):
        tracker = TrustTracker()
        app_id = uuid4()

        tracker.record_outcome(app_id, Outcome.COMPLETE)
        metrics = tracker.get_metrics(app_id)

        assert metrics.total_tasks == 1
        assert metrics.successful_tasks == 1
        assert metrics.consecutive_successes == 1

    def test_record_saturated_as_success(self):
        tracker = TrustTracker()
        app_id = uuid4()

        tracker.record_outcome(app_id, Outcome.SATURATED)
        metrics = tracker.get_metrics(app_id)

        assert metrics.successful_tasks == 1

    def test_record_failure(self):
        tracker = TrustTracker()
        app_id = uuid4()

        tracker.record_outcome(app_id, Outcome.INCONCLUSIVE)
        metrics = tracker.get_metrics(app_id)

        assert metrics.total_tasks == 1
        assert metrics.failed_tasks == 1
        assert metrics.consecutive_successes == 0

    def test_record_bounded_as_failure(self):
        tracker = TrustTracker()
        app_id = uuid4()

        tracker.record_outcome(app_id, Outcome.BOUNDED)
        metrics = tracker.get_metrics(app_id)

        assert metrics.failed_tasks == 1

    def test_consecutive_successes_reset_on_failure(self):
        tracker = TrustTracker()
        app_id = uuid4()

        # Record 3 successes
        for _ in range(3):
            tracker.record_outcome(app_id, Outcome.COMPLETE)

        metrics = tracker.get_metrics(app_id)
        assert metrics.consecutive_successes == 3

        # One failure resets the counter
        tracker.record_outcome(app_id, Outcome.INCONCLUSIVE)

        metrics = tracker.get_metrics(app_id)
        assert metrics.consecutive_successes == 0
        assert metrics.successful_tasks == 3
        assert metrics.failed_tasks == 1

    def test_timestamps_updated(self):
        tracker = TrustTracker()
        app_id = uuid4()

        metrics_before = tracker.get_metrics(app_id)
        original_updated = metrics_before.updated_at

        tracker.record_outcome(app_id, Outcome.COMPLETE)
        metrics_after = tracker.get_metrics(app_id)

        assert metrics_after.last_task_at is not None
        assert metrics_after.updated_at >= original_updated


class TestTrustTrackerSuggestions:
    """Tests for TrustTracker suggestions."""

    def test_no_suggestion_for_new_user(self):
        tracker = TrustTracker()
        app_id = uuid4()

        suggestion = tracker.get_suggestion(app_id)
        assert suggestion is None

    def test_no_suggestion_below_threshold(self):
        tracker = TrustTracker()
        app_id = uuid4()

        # 4 successes (need 5)
        for _ in range(4):
            tracker.record_outcome(app_id, Outcome.COMPLETE)

        suggestion = tracker.get_suggestion(app_id)
        assert suggestion is None

    def test_suggestion_for_level_0_upgrade(self):
        tracker = TrustTracker()
        app_id = uuid4()

        # 6 successes (need 5) with 100% rate (need 80%)
        for _ in range(6):
            tracker.record_outcome(app_id, Outcome.COMPLETE)

        suggestion = tracker.get_suggestion(app_id)
        assert suggestion is not None
        assert suggestion.current_level == 0
        assert suggestion.suggested_level == 1
        assert "semi-autonomous" in suggestion.reason.lower()

    def test_suggestion_for_level_1_upgrade(self):
        tracker = TrustTracker()
        app_id = uuid4()

        # First reach level 1
        tracker.update_trust_level(app_id, 1)

        # 12 successes at level 1 (need 10)
        for _ in range(12):
            tracker.record_outcome(app_id, Outcome.COMPLETE)

        suggestion = tracker.get_suggestion(app_id)
        assert suggestion is not None
        assert suggestion.current_level == 1
        assert suggestion.suggested_level == 2
        assert "autonomous" in suggestion.reason.lower()


class TestTrustTrackerLevelUpdate:
    """Tests for TrustTracker level updates."""

    def test_update_trust_level(self):
        tracker = TrustTracker()
        app_id = uuid4()

        metrics = tracker.update_trust_level(app_id, 1)
        assert metrics.current_trust_level == 1

    def test_update_trust_level_invalid(self):
        tracker = TrustTracker()
        app_id = uuid4()

        with pytest.raises(ValueError):
            tracker.update_trust_level(app_id, 3)

        with pytest.raises(ValueError):
            tracker.update_trust_level(app_id, -1)

    def test_reset_metrics(self):
        tracker = TrustTracker()
        app_id = uuid4()

        # Record some activity
        tracker.record_outcome(app_id, Outcome.COMPLETE)
        assert tracker.get_metrics(app_id).total_tasks == 1

        # Reset
        tracker.reset_metrics(app_id)

        # Fresh metrics
        assert tracker.get_metrics(app_id).total_tasks == 0


class TestTrustLevelUpdateModel:
    """Tests for TrustLevelUpdate model."""

    def test_valid_levels(self):
        for level in [0, 1, 2]:
            update = TrustLevelUpdate(trust_level=level)
            assert update.trust_level == level

    def test_invalid_level_above(self):
        with pytest.raises(ValueError):
            TrustLevelUpdate(trust_level=3)

    def test_invalid_level_below(self):
        with pytest.raises(ValueError):
            TrustLevelUpdate(trust_level=-1)


class TestTrustSuggestionModel:
    """Tests for TrustSuggestion model."""

    def test_suggestion_structure(self):
        metrics = TrustMetrics(
            app_id=uuid4(),
            total_tasks=10,
            successful_tasks=8,
            consecutive_successes=5,
        )

        suggestion = TrustSuggestion(
            current_level=0,
            suggested_level=1,
            reason="Good track record",
            metrics=metrics,
        )

        assert suggestion.current_level == 0
        assert suggestion.suggested_level == 1
        assert suggestion.metrics.success_rate == 0.8
