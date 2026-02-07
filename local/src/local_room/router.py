"""Task routing with offline fallback (Phase 4B).

Decides whether to handle tasks locally or escalate to server.
Provides offline fallback when server is unavailable.
"""

import asyncio
import logging
from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field

from local_room.privacy import PrivacyClassifier, PrivacyAssessment, PrivacyLevel

logger = logging.getLogger(__name__)


class RoutingDecision(str, Enum):
    """Where should a task be routed?"""

    LOCAL = "local"        # Handle locally
    SERVER = "server"      # Send to server
    ESCALATE = "escalate"  # Local tried, needs server


class EscalationReason(str, Enum):
    """Why is a task being escalated to server?"""

    NEEDS_WEB_SEARCH = "needs_web_search"
    NEEDS_RESEARCH = "needs_research"
    COMPLEX_QUERY = "complex_query"
    LOW_CONFIDENCE = "low_confidence"
    EXPLICIT_REQUEST = "explicit_request"
    CAPABILITY_MISSING = "capability_missing"


class RoutingResult(BaseModel):
    """Result of routing decision."""

    decision: RoutingDecision
    reason: str
    privacy: PrivacyAssessment | None = None
    server_available: bool = True
    escalation_reason: EscalationReason | None = None
    suggested_instrument: str | None = None


class ServerStatus(BaseModel):
    """Status of the server connection."""

    available: bool = False
    last_check: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: int | None = None
    error: str | None = None
    consecutive_failures: int = 0


class TaskRouter:
    """Routes tasks between local and server.

    Decision logic:
    1. Privacy-sensitive → local (if capable)
    2. Server unavailable → local (offline fallback)
    3. Local can't handle → escalate to server
    4. Default → server (more capable)
    """

    def __init__(
        self,
        server_url: str,
        local_capabilities: set[str] | None = None,
        prefer_local: bool = False,
        health_check_interval: int = 30,
    ) -> None:
        """Initialize the router.

        Args:
            server_url: URL of the Loop Symphony server
            local_capabilities: What can the local room do?
            prefer_local: If True, prefer local even when server available
            health_check_interval: Seconds between server health checks
        """
        self._server_url = server_url.rstrip("/")
        self._local_capabilities = local_capabilities or {"reasoning"}
        self._prefer_local = prefer_local
        self._health_check_interval = health_check_interval

        self._privacy_classifier = PrivacyClassifier()
        self._server_status = ServerStatus()
        self._health_check_task: asyncio.Task | None = None

    @property
    def server_available(self) -> bool:
        """Is the server currently available?"""
        return self._server_status.available

    async def start(self) -> None:
        """Start the router (begins health check loop)."""
        await self._check_server_health()
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop(self) -> None:
        """Stop the router."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

    async def route(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        required_capabilities: set[str] | None = None,
        force_local: bool = False,
        force_server: bool = False,
    ) -> RoutingResult:
        """Decide where to route a task.

        Args:
            query: The query to route
            context: Optional context
            required_capabilities: Capabilities needed for this task
            force_local: Force local execution
            force_server: Force server execution

        Returns:
            RoutingResult with decision and reasoning
        """
        # Check privacy first
        privacy = self._privacy_classifier.classify(query, context)

        # Force local requested
        if force_local:
            return RoutingResult(
                decision=RoutingDecision.LOCAL,
                reason="Local execution explicitly requested",
                privacy=privacy,
                server_available=self._server_status.available,
            )

        # Privacy requires local
        if privacy.should_stay_local:
            if self._can_handle_locally(required_capabilities):
                return RoutingResult(
                    decision=RoutingDecision.LOCAL,
                    reason=f"Privacy-sensitive content: {privacy.reason}",
                    privacy=privacy,
                    server_available=self._server_status.available,
                    suggested_instrument="local_note",
                )
            else:
                # Can't handle locally, but privacy requires it
                # Return local anyway with degraded capability warning
                return RoutingResult(
                    decision=RoutingDecision.LOCAL,
                    reason=f"Privacy requires local, but limited capability. {privacy.reason}",
                    privacy=privacy,
                    server_available=self._server_status.available,
                    suggested_instrument="local_note",
                )

        # Force server requested
        if force_server:
            if self._server_status.available:
                return RoutingResult(
                    decision=RoutingDecision.SERVER,
                    reason="Server execution explicitly requested",
                    privacy=privacy,
                    server_available=True,
                )
            else:
                # Server requested but unavailable - fall back to local
                return RoutingResult(
                    decision=RoutingDecision.LOCAL,
                    reason="Server requested but unavailable, falling back to local",
                    privacy=privacy,
                    server_available=False,
                )

        # Server unavailable - offline fallback
        if not self._server_status.available:
            return RoutingResult(
                decision=RoutingDecision.LOCAL,
                reason=f"Server unavailable: {self._server_status.error or 'offline'}",
                privacy=privacy,
                server_available=False,
                suggested_instrument="local_note",
            )

        # Check if local can handle the required capabilities
        if required_capabilities and not self._can_handle_locally(required_capabilities):
            return RoutingResult(
                decision=RoutingDecision.SERVER,
                reason=f"Local missing capabilities: {required_capabilities - self._local_capabilities}",
                privacy=privacy,
                server_available=True,
            )

        # Check for signals that need server
        needs_server = self._needs_server_capabilities(query)
        if needs_server:
            return RoutingResult(
                decision=RoutingDecision.SERVER,
                reason=needs_server,
                privacy=privacy,
                server_available=True,
            )

        # Prefer local mode
        if self._prefer_local and self._can_handle_locally(required_capabilities):
            return RoutingResult(
                decision=RoutingDecision.LOCAL,
                reason="Prefer local mode enabled",
                privacy=privacy,
                server_available=True,
                suggested_instrument="local_note",
            )

        # Default: use server (more capable)
        return RoutingResult(
            decision=RoutingDecision.SERVER,
            reason="Default routing to server for full capability",
            privacy=privacy,
            server_available=True,
        )

    def _can_handle_locally(self, required: set[str] | None) -> bool:
        """Check if local room can handle required capabilities."""
        if not required:
            return True
        return required.issubset(self._local_capabilities)

    def _needs_server_capabilities(self, query: str) -> str | None:
        """Check if query signals need for server capabilities."""
        query_lower = query.lower()

        # Web search signals
        search_signals = [
            "search for", "look up", "find out", "what's the latest",
            "current", "today's", "recent", "news about",
        ]
        if any(signal in query_lower for signal in search_signals):
            return "Query suggests web search needed"

        # Research signals
        research_signals = [
            "research", "investigate", "deep dive", "comprehensive",
            "analyze all", "compare multiple", "thorough analysis",
        ]
        if any(signal in query_lower for signal in research_signals):
            return "Query suggests deep research needed"

        return None

    async def escalate(
        self,
        query: str,
        reason: EscalationReason,
        local_result: dict[str, Any] | None = None,
    ) -> RoutingResult:
        """Mark a task for escalation to server.

        Called when local execution determines server is needed.

        Args:
            query: The original query
            reason: Why escalation is needed
            local_result: Optional partial result from local

        Returns:
            RoutingResult indicating escalation
        """
        return RoutingResult(
            decision=RoutingDecision.ESCALATE,
            reason=f"Local execution escalating: {reason.value}",
            server_available=self._server_status.available,
            escalation_reason=reason,
        )

    async def _health_check_loop(self) -> None:
        """Periodically check server health."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._check_server_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def _check_server_health(self) -> None:
        """Check if server is available."""
        try:
            start = datetime.now(UTC)
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._server_url}/health")

                latency = int((datetime.now(UTC) - start).total_seconds() * 1000)

                if response.status_code == 200:
                    self._server_status = ServerStatus(
                        available=True,
                        last_check=datetime.now(UTC),
                        latency_ms=latency,
                        consecutive_failures=0,
                    )
                else:
                    self._server_status.available = False
                    self._server_status.error = f"Status {response.status_code}"
                    self._server_status.consecutive_failures += 1

        except httpx.ConnectError:
            self._server_status.available = False
            self._server_status.error = "Connection refused"
            self._server_status.consecutive_failures += 1
            self._server_status.last_check = datetime.now(UTC)

        except httpx.TimeoutException:
            self._server_status.available = False
            self._server_status.error = "Timeout"
            self._server_status.consecutive_failures += 1
            self._server_status.last_check = datetime.now(UTC)

        except Exception as e:
            self._server_status.available = False
            self._server_status.error = str(e)
            self._server_status.consecutive_failures += 1
            self._server_status.last_check = datetime.now(UTC)

    def get_status(self) -> dict[str, Any]:
        """Get current router status."""
        return {
            "server_available": self._server_status.available,
            "server_url": self._server_url,
            "last_check": self._server_status.last_check.isoformat(),
            "latency_ms": self._server_status.latency_ms,
            "consecutive_failures": self._server_status.consecutive_failures,
            "error": self._server_status.error,
            "prefer_local": self._prefer_local,
            "local_capabilities": list(self._local_capabilities),
        }
