"""System health models for autonomic monitoring (Phase 3E)."""

from datetime import datetime, UTC
from enum import Enum

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    """Overall health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"  # Some components unhealthy but system operational
    CRITICAL = "critical"  # System unable to function


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None
    last_check: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SystemHealth(BaseModel):
    """Overall system health status.

    Used by the autonomic layer to track health across all components.
    Only critical errors should surface to users ("pain response").
    """

    status: HealthStatus = HealthStatus.HEALTHY
    components: dict[str, ComponentHealth] = Field(default_factory=dict)
    last_check: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Autonomic layer stats
    uptime_seconds: float = 0.0
    health_checks_run: int = 0
    heartbeats_processed: int = 0

    # Error tracking for "pain response"
    consecutive_failures: int = 0
    last_error: str | None = None
    last_error_at: datetime | None = None

    @property
    def healthy_components(self) -> list[str]:
        """List of healthy component names."""
        return [name for name, comp in self.components.items() if comp.healthy]

    @property
    def unhealthy_components(self) -> list[str]:
        """List of unhealthy component names."""
        return [name for name, comp in self.components.items() if not comp.healthy]

    def update_component(
        self,
        name: str,
        healthy: bool,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        """Update health status for a component."""
        self.components[name] = ComponentHealth(
            name=name,
            healthy=healthy,
            latency_ms=latency_ms,
            error=error,
        )
        self._recalculate_status()

    def _recalculate_status(self) -> None:
        """Recalculate overall status based on component health."""
        if not self.components:
            self.status = HealthStatus.HEALTHY
            return

        unhealthy = self.unhealthy_components

        if not unhealthy:
            self.status = HealthStatus.HEALTHY
            self.consecutive_failures = 0
        elif "database" in unhealthy:
            # Database is critical - system cannot function without it
            self.status = HealthStatus.CRITICAL
            self.consecutive_failures += 1
        else:
            # Other components degraded but system can continue
            self.status = HealthStatus.DEGRADED
            self.consecutive_failures += 1

    def record_error(self, error: str) -> None:
        """Record an error occurrence."""
        self.last_error = error
        self.last_error_at = datetime.now(UTC)
        self.consecutive_failures += 1

    def should_alert(self, threshold: int = 3) -> bool:
        """Whether we should surface this error to users.

        Only alert for critical issues after repeated failures.
        This implements the "pain response" - only surface when necessary.

        Args:
            threshold: Number of consecutive failures before alerting

        Returns:
            True if we should alert the user
        """
        return (
            self.status == HealthStatus.CRITICAL
            and self.consecutive_failures >= threshold
        )
