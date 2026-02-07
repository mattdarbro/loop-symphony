"""Tests for privacy classifier and router (Phase 4B)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from local_room.privacy import (
    PrivacyClassifier,
    PrivacyCategory,
    PrivacyLevel,
    PrivacyAssessment,
)
from local_room.router import (
    TaskRouter,
    RoutingDecision,
    EscalationReason,
    ServerStatus,
)


class TestPrivacyCategory:
    """Tests for PrivacyCategory enum."""

    def test_categories(self):
        assert PrivacyCategory.HEALTH.value == "health"
        assert PrivacyCategory.FINANCIAL.value == "financial"
        assert PrivacyCategory.PERSONAL.value == "personal"
        assert PrivacyCategory.IDENTITY.value == "identity"


class TestPrivacyLevel:
    """Tests for PrivacyLevel enum."""

    def test_levels(self):
        assert PrivacyLevel.PUBLIC.value == "public"
        assert PrivacyLevel.SENSITIVE.value == "sensitive"
        assert PrivacyLevel.PRIVATE.value == "private"
        assert PrivacyLevel.CONFIDENTIAL.value == "confidential"


class TestPrivacyClassifier:
    """Tests for PrivacyClassifier."""

    def test_public_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("What is the capital of France?")

        assert result.level == PrivacyLevel.PUBLIC
        assert PrivacyCategory.NONE in result.categories
        assert result.should_stay_local is False

    def test_health_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("I have a headache and my doctor recommended aspirin")

        assert result.level == PrivacyLevel.PRIVATE
        assert PrivacyCategory.HEALTH in result.categories
        assert result.should_stay_local is True

    def test_financial_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("My salary is $50000 and I need to budget")

        assert result.level == PrivacyLevel.PRIVATE
        assert PrivacyCategory.FINANCIAL in result.categories
        assert result.should_stay_local is True

    def test_personal_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("I feel sad about my relationship with my boyfriend")

        assert result.level == PrivacyLevel.SENSITIVE
        assert PrivacyCategory.PERSONAL in result.categories

    def test_identity_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("My SSN is 123-45-6789")

        assert result.level == PrivacyLevel.CONFIDENTIAL
        assert PrivacyCategory.IDENTITY in result.categories
        assert result.should_stay_local is True

    def test_location_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("I'm at my home right now")

        assert PrivacyCategory.LOCATION in result.categories

    def test_work_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("This is confidential company information")

        assert PrivacyCategory.WORK in result.categories

    def test_legal_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("My lawyer said I should sue")

        assert PrivacyCategory.LEGAL in result.categories

    def test_multiple_categories(self):
        classifier = PrivacyClassifier()
        result = classifier.classify(
            "My doctor said my blood pressure affects my income tax situation"
        )

        # Should detect both health and financial
        assert len(result.categories) >= 2

    def test_is_sensitive(self):
        classifier = PrivacyClassifier()

        assert classifier.is_sensitive("What is 2+2?") is False
        assert classifier.is_sensitive("My medication dosage") is True

    def test_must_stay_local(self):
        classifier = PrivacyClassifier()

        assert classifier.must_stay_local("Weather today") is False
        assert classifier.must_stay_local("My SSN is 123-45-6789") is True

    def test_strict_mode(self):
        classifier = PrivacyClassifier(strict_mode=True)
        result = classifier.classify("I feel happy today")

        # In strict mode, even SENSITIVE should stay local
        assert result.should_stay_local is True


class TestServerStatus:
    """Tests for ServerStatus model."""

    def test_defaults(self):
        status = ServerStatus()
        assert status.available is False
        assert status.consecutive_failures == 0

    def test_available(self):
        status = ServerStatus(available=True, latency_ms=50)
        assert status.available is True
        assert status.latency_ms == 50


class TestTaskRouter:
    """Tests for TaskRouter."""

    def test_init(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        assert router._server_url == "http://localhost:8000"

    @pytest.mark.asyncio
    async def test_route_privacy_sensitive(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        # Simulate server available
        router._server_status.available = True

        result = await router.route("My doctor prescribed medication")

        assert result.decision == RoutingDecision.LOCAL
        assert result.privacy.should_stay_local is True
        assert "privacy" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_route_server_unavailable(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        # Server not available
        router._server_status.available = False
        router._server_status.error = "Connection refused"

        result = await router.route("What is 2+2?")

        assert result.decision == RoutingDecision.LOCAL
        assert result.server_available is False
        assert "unavailable" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_route_force_local(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        router._server_status.available = True

        result = await router.route("Public question", force_local=True)

        assert result.decision == RoutingDecision.LOCAL
        assert "explicitly requested" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_route_force_server(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        router._server_status.available = True

        result = await router.route("Public question", force_server=True)

        assert result.decision == RoutingDecision.SERVER

    @pytest.mark.asyncio
    async def test_route_force_server_unavailable(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        router._server_status.available = False

        result = await router.route("Public question", force_server=True)

        # Falls back to local
        assert result.decision == RoutingDecision.LOCAL

    @pytest.mark.asyncio
    async def test_route_needs_web_search(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        router._server_status.available = True

        result = await router.route("Search for the latest news about AI")

        assert result.decision == RoutingDecision.SERVER
        assert "search" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_route_needs_research(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        router._server_status.available = True

        result = await router.route("Do a comprehensive research on quantum computing")

        assert result.decision == RoutingDecision.SERVER
        assert "research" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_route_prefer_local(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
            prefer_local=True,
        )
        router._server_status.available = True

        result = await router.route("What is 2+2?")

        assert result.decision == RoutingDecision.LOCAL
        assert "prefer local" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_route_missing_capability(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
        )
        router._server_status.available = True

        result = await router.route(
            "Search query",
            required_capabilities={"web_search"},
        )

        assert result.decision == RoutingDecision.SERVER
        assert "capabilities" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_escalate(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
        )

        result = await router.escalate(
            "Complex query",
            reason=EscalationReason.NEEDS_WEB_SEARCH,
        )

        assert result.decision == RoutingDecision.ESCALATE
        assert result.escalation_reason == EscalationReason.NEEDS_WEB_SEARCH

    def test_get_status(self):
        router = TaskRouter(
            server_url="http://localhost:8000",
            local_capabilities={"reasoning"},
            prefer_local=True,
        )
        router._server_status.available = True
        router._server_status.latency_ms = 50

        status = router.get_status()

        assert status["server_available"] is True
        assert status["latency_ms"] == 50
        assert status["prefer_local"] is True
        assert "reasoning" in status["local_capabilities"]

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        router = TaskRouter(server_url="http://localhost:8000")

        with patch("local_room.router.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            await router._check_server_health()

            assert router._server_status.available is True
            assert router._server_status.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        router = TaskRouter(server_url="http://localhost:8000")

        with patch("local_room.router.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            await router._check_server_health()

            assert router._server_status.available is False
            assert router._server_status.consecutive_failures == 1
