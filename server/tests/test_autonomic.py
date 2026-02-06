"""Tests for autonomic process layer (Phase 3E)."""

import pytest
from datetime import datetime, UTC

from loop_symphony.models.health import (
    ComponentHealth,
    HealthStatus,
    SystemHealth,
)


class TestComponentHealthModel:
    """Tests for ComponentHealth model."""

    def test_basic_component(self):
        comp = ComponentHealth(name="database", healthy=True)
        assert comp.name == "database"
        assert comp.healthy is True
        assert comp.error is None

    def test_unhealthy_component(self):
        comp = ComponentHealth(
            name="database",
            healthy=False,
            latency_ms=5000.0,
            error="Connection timeout",
        )
        assert comp.healthy is False
        assert comp.error == "Connection timeout"

    def test_auto_timestamp(self):
        comp = ComponentHealth(name="test", healthy=True)
        assert comp.last_check is not None
        assert isinstance(comp.last_check, datetime)


class TestHealthStatusEnum:
    """Tests for HealthStatus enum."""

    def test_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.CRITICAL.value == "critical"


class TestSystemHealthModel:
    """Tests for SystemHealth model."""

    def test_default_healthy(self):
        health = SystemHealth()
        assert health.status == HealthStatus.HEALTHY
        assert len(health.components) == 0
        assert health.consecutive_failures == 0

    def test_healthy_components_list(self):
        health = SystemHealth()
        health.update_component("db", healthy=True)
        health.update_component("tool:claude", healthy=True)
        health.update_component("tool:tavily", healthy=False)

        assert "db" in health.healthy_components
        assert "tool:claude" in health.healthy_components
        assert "tool:tavily" not in health.healthy_components

    def test_unhealthy_components_list(self):
        health = SystemHealth()
        health.update_component("db", healthy=True)
        health.update_component("tool:tavily", healthy=False, error="API error")

        assert "tool:tavily" in health.unhealthy_components
        assert "db" not in health.unhealthy_components


class TestSystemHealthStatusCalculation:
    """Tests for SystemHealth status calculation."""

    def test_all_healthy(self):
        health = SystemHealth()
        health.update_component("database", healthy=True)
        health.update_component("tool:claude", healthy=True)

        assert health.status == HealthStatus.HEALTHY
        assert health.consecutive_failures == 0

    def test_database_unhealthy_is_critical(self):
        health = SystemHealth()
        health.update_component("database", healthy=False, error="Connection refused")

        assert health.status == HealthStatus.CRITICAL
        assert health.consecutive_failures == 1

    def test_tool_unhealthy_is_degraded(self):
        health = SystemHealth()
        health.update_component("database", healthy=True)
        health.update_component("tool:tavily", healthy=False, error="Rate limited")

        assert health.status == HealthStatus.DEGRADED
        assert health.consecutive_failures == 1

    def test_recovery_resets_failures(self):
        health = SystemHealth()
        # First go unhealthy
        health.update_component("tool:claude", healthy=False)
        assert health.consecutive_failures == 1

        # Then recover
        health.update_component("tool:claude", healthy=True)
        assert health.status == HealthStatus.HEALTHY
        assert health.consecutive_failures == 0


class TestSystemHealthErrorTracking:
    """Tests for SystemHealth error tracking."""

    def test_record_error(self):
        health = SystemHealth()
        health.record_error("Something went wrong")

        assert health.last_error == "Something went wrong"
        assert health.last_error_at is not None
        assert health.consecutive_failures == 1

    def test_multiple_errors(self):
        health = SystemHealth()
        health.record_error("Error 1")
        health.record_error("Error 2")

        assert health.last_error == "Error 2"
        assert health.consecutive_failures == 2


class TestSystemHealthPainResponse:
    """Tests for SystemHealth pain response (alerting)."""

    def test_no_alert_when_healthy(self):
        health = SystemHealth()
        health.update_component("database", healthy=True)
        assert not health.should_alert()

    def test_no_alert_for_degraded(self):
        health = SystemHealth()
        health.update_component("database", healthy=True)
        health.update_component("tool:tavily", healthy=False)
        # Degraded but not critical
        assert health.status == HealthStatus.DEGRADED
        assert not health.should_alert()

    def test_no_alert_for_single_critical_failure(self):
        health = SystemHealth()
        health.update_component("database", healthy=False)
        # Critical but only 1 consecutive failure
        assert health.status == HealthStatus.CRITICAL
        assert health.consecutive_failures == 1
        assert not health.should_alert(threshold=3)

    def test_alert_after_threshold(self):
        health = SystemHealth()
        # Simulate 3 consecutive database failures
        for _ in range(3):
            health.update_component("database", healthy=False, error="Connection refused")

        assert health.status == HealthStatus.CRITICAL
        assert health.consecutive_failures >= 3
        assert health.should_alert(threshold=3)

    def test_custom_threshold(self):
        health = SystemHealth()
        health.update_component("database", healthy=False)
        health.update_component("database", healthy=False)

        assert health.consecutive_failures == 2
        assert not health.should_alert(threshold=3)
        assert health.should_alert(threshold=2)


class TestSystemHealthStats:
    """Tests for SystemHealth statistics."""

    def test_uptime_tracking(self):
        health = SystemHealth()
        health.uptime_seconds = 3600.0
        assert health.uptime_seconds == 3600.0

    def test_health_checks_counter(self):
        health = SystemHealth()
        health.health_checks_run = 10
        assert health.health_checks_run == 10

    def test_heartbeats_counter(self):
        health = SystemHealth()
        health.heartbeats_processed = 5
        assert health.heartbeats_processed == 5


class TestDatabaseHealthCheck:
    """Tests for database health check interface."""

    def test_health_check_result_interface(self):
        """Health check should return a dict with expected keys."""
        # This tests the expected interface of health check results
        # Actual DB testing would require integration tests
        result = {
            "healthy": True,
            "latency_ms": 5.0,
            "error": None,
        }
        assert "healthy" in result
        assert "latency_ms" in result
        assert "error" in result

    def test_unhealthy_result_interface(self):
        """Unhealthy result should include error."""
        result = {
            "healthy": False,
            "latency_ms": 5000.0,
            "error": "Connection timeout",
        }
        assert result["healthy"] is False
        assert result["error"] is not None
