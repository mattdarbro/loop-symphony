"""Tests for room-aware conductor routing (Phase 4C)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from loop_symphony.manager.conductor import Conductor
from loop_symphony.manager.room_client import RoomClient, RoomDelegationResult
from loop_symphony.manager.room_registry import (
    RoomInfo,
    RoomRegistry,
    RoomRegistration,
)
from loop_symphony.models.finding import ExecutionMetadata
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskRequest, TaskResponse, TaskContext, TaskPreferences
from loop_symphony.privacy.classifier import PrivacyLevel


def _make_registry_with_rooms() -> RoomRegistry:
    """Create a RoomRegistry with a server and a local room."""
    registry = RoomRegistry()

    # Register server
    registry.register_server(
        capabilities={"reasoning", "synthesis", "analysis", "vision", "web_search"},
        instruments=["note", "research", "synthesis", "vision"],
    )

    # Register local room
    registry.register(RoomRegistration(
        room_id="local-1",
        room_name="Local Room",
        room_type="local",
        url="http://localhost:8001",
        capabilities=["reasoning"],
        instruments=["local_note"],
    ))

    return registry


class TestConductorRoomRegistryAcceptance:
    """Tests that Conductor accepts and uses room_registry parameter."""

    def test_conductor_accepts_room_registry(self):
        room_registry = RoomRegistry()
        conductor = Conductor(room_registry=room_registry)
        assert conductor.room_registry is room_registry

    def test_conductor_works_without_room_registry(self):
        conductor = Conductor()
        assert conductor.room_registry is None

    def test_conductor_works_with_both_registries(self):
        room_registry = RoomRegistry()
        conductor = Conductor(room_registry=room_registry)
        assert conductor.room_registry is room_registry
        assert conductor.registry is None


class TestServerSelfRegistration:
    """Tests for RoomRegistry.register_server()."""

    def test_register_server(self):
        registry = RoomRegistry()
        room = registry.register_server(
            capabilities={"reasoning", "web_search"},
            instruments=["note", "research"],
        )
        assert room.room_id == "server"
        assert room.room_type == "server"
        assert room.status == "online"
        assert "reasoning" in room.capabilities
        assert "web_search" in room.capabilities

    def test_server_room_always_online(self):
        registry = RoomRegistry()
        registry.register_server(
            capabilities={"reasoning"},
            instruments=["note"],
        )
        # Server room should never be timed out
        online = registry.get_online_rooms()
        assert any(r.room_id == "server" for r in online)

    def test_server_competes_in_scoring(self):
        registry = _make_registry_with_rooms()

        # When web_search is required, only server qualifies
        best = registry.get_best_room_for_task(
            required_capabilities={"web_search"},
        )
        assert best.room_id == "server"


class TestDegradationStatus:
    """Tests for RoomRegistry.get_degradation_status()."""

    def test_all_online(self):
        registry = _make_registry_with_rooms()
        status = registry.get_degradation_status()
        assert status["fully_operational"] is True
        assert len(status["offline_rooms"]) == 0
        assert len(status["degraded_rooms"]) == 0

    def test_with_offline_room(self):
        registry = _make_registry_with_rooms()
        # Simulate local room going offline
        room = registry.get_room("local-1")
        room.status = "offline"

        status = registry.get_degradation_status()
        assert status["fully_operational"] is False
        assert "local-1" in status["offline_rooms"]
        assert "server" in status["online_rooms"]

    def test_capabilities_available(self):
        registry = _make_registry_with_rooms()
        status = registry.get_degradation_status()
        assert "reasoning" in status["capabilities_available"]
        assert "web_search" in status["capabilities_available"]


class TestRoomSelection:
    """Tests for Conductor._select_room()."""

    @pytest.mark.asyncio
    async def test_public_query_prefers_server(self):
        """Public queries go to server (more capabilities)."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        request = TaskRequest(query="What is the capital of France?")
        room = await conductor._select_room(request, "note")

        # Server has more capabilities, so scores higher for public queries
        assert room is not None
        assert room.room_id == "server"

    @pytest.mark.asyncio
    async def test_privacy_sensitive_query_prefers_local(self):
        """Private queries prefer local rooms."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        request = TaskRequest(query="My doctor said I need medication for anxiety")
        room = await conductor._select_room(request, "note")

        # Privacy = should_stay_local, so prefer_local=True -> local wins
        assert room is not None
        assert room.room_id == "local-1"

    @pytest.mark.asyncio
    async def test_web_search_routes_to_server(self):
        """Tasks requiring web_search go to server only."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        request = TaskRequest(query="Research the latest AI trends")
        room = await conductor._select_room(request, "research")

        # Research instrument requires web_search; only server has it
        assert room is not None
        assert room.room_id == "server"

    @pytest.mark.asyncio
    async def test_no_rooms_returns_none(self):
        """Empty registry returns None."""
        registry = RoomRegistry()
        conductor = Conductor(room_registry=registry)

        request = TaskRequest(query="Hello")
        room = await conductor._select_room(request, "note")
        assert room is None


class TestConductorDelegation:
    """Tests for full execute() with room delegation."""

    @pytest.mark.asyncio
    async def test_delegates_to_local_room_for_private_query(self):
        """Privacy-sensitive task gets delegated to local room."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        # Mock the room client
        mock_response = TaskResponse(
            request_id="test-id",
            outcome=Outcome.COMPLETE,
            findings=[],
            summary="Local result",
            confidence=0.8,
            metadata=ExecutionMetadata(
                instrument_used="room:local-1/local_note",
                iterations=1,
                duration_ms=100,
                process_type=ProcessType.SEMI_AUTONOMIC,
            ),
        )

        mock_result = RoomDelegationResult(
            success=True,
            response=mock_response,
            room_id="local-1",
            latency_ms=100,
        )

        with patch.object(
            RoomClient, "delegate", new_callable=AsyncMock, return_value=mock_result
        ):
            request = TaskRequest(query="My SSN is 123-45-6789")
            response = await conductor.execute(request)

        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Local result"
        assert response.metadata.room_id == "local-1"

    @pytest.mark.asyncio
    async def test_falls_back_to_server_on_delegation_failure(self):
        """When delegation fails, fall back to local server execution."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        # Mock delegation to fail
        mock_result = RoomDelegationResult(
            success=False,
            error="Connection refused",
            room_id="local-1",
            latency_ms=50,
        )

        # Mock the note instrument for server fallback
        mock_instrument = MagicMock()
        mock_instrument.required_capabilities = frozenset({"reasoning"})
        mock_execute = AsyncMock()
        from loop_symphony.instruments.base import InstrumentResult
        from loop_symphony.models.outcome import Outcome as OutcomeEnum
        mock_execute.return_value = InstrumentResult(
            outcome=OutcomeEnum.COMPLETE,
            findings=[],
            summary="Server fallback result",
            confidence=0.75,
            iterations=1,
        )
        mock_instrument.execute = mock_execute
        conductor.instruments["note"] = mock_instrument

        with patch.object(
            RoomClient, "delegate", new_callable=AsyncMock, return_value=mock_result
        ):
            request = TaskRequest(query="My doctor prescribed medication")
            response = await conductor.execute(request)

        # Should have fallen back to server execution
        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Server fallback result"
        # Failover should be recorded
        assert len(response.metadata.failover_events) == 1
        assert response.metadata.failover_events[0]["original_room_id"] == "local-1"
        assert response.metadata.failover_events[0]["fallback_room_id"] == "server"

    @pytest.mark.asyncio
    async def test_no_delegation_for_server_room(self):
        """Tasks routed to server room execute locally (no HTTP delegation)."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        # Mock the note instrument
        mock_instrument = MagicMock()
        mock_instrument.required_capabilities = frozenset({"reasoning"})
        mock_execute = AsyncMock()
        from loop_symphony.instruments.base import InstrumentResult
        from loop_symphony.models.outcome import Outcome as OutcomeEnum
        mock_execute.return_value = InstrumentResult(
            outcome=OutcomeEnum.COMPLETE,
            findings=[],
            summary="Server result",
            confidence=0.9,
            iterations=1,
        )
        mock_instrument.execute = mock_execute
        conductor.instruments["note"] = mock_instrument

        request = TaskRequest(query="What is Python?")
        response = await conductor.execute(request)

        # Should execute locally, not delegate
        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Server result"
        assert response.metadata.room_id == "server"

    @pytest.mark.asyncio
    async def test_no_room_registry_skips_room_logic(self):
        """Without room_registry, Conductor behaves as before (backward compat)."""
        conductor = Conductor()  # No room_registry

        # Mock the note instrument
        mock_instrument = MagicMock()
        mock_instrument.required_capabilities = frozenset({"reasoning"})
        mock_execute = AsyncMock()
        from loop_symphony.instruments.base import InstrumentResult
        from loop_symphony.models.outcome import Outcome as OutcomeEnum
        mock_execute.return_value = InstrumentResult(
            outcome=OutcomeEnum.COMPLETE,
            findings=[],
            summary="Direct result",
            confidence=0.9,
            iterations=1,
        )
        mock_instrument.execute = mock_execute
        conductor.instruments["note"] = mock_instrument

        request = TaskRequest(query="Hello world")
        response = await conductor.execute(request)

        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Direct result"

    @pytest.mark.asyncio
    async def test_metadata_includes_room_id_for_server_execution(self):
        """Metadata tracks room_id even for server-local execution."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        mock_instrument = MagicMock()
        mock_instrument.required_capabilities = frozenset({"reasoning"})
        mock_execute = AsyncMock()
        from loop_symphony.instruments.base import InstrumentResult
        from loop_symphony.models.outcome import Outcome as OutcomeEnum
        mock_execute.return_value = InstrumentResult(
            outcome=OutcomeEnum.COMPLETE,
            findings=[],
            summary="Done",
            confidence=0.9,
            iterations=1,
        )
        mock_instrument.execute = mock_execute
        conductor.instruments["note"] = mock_instrument

        request = TaskRequest(query="What is 2+2?")
        response = await conductor.execute(request)

        assert response.metadata.room_id == "server"
        assert response.metadata.failover_events == []
