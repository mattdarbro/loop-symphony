"""Tests for graceful degradation in cross-room routing (Phase 4C)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.manager.conductor import Conductor
from loop_symphony.manager.room_client import RoomClient, RoomDelegationResult
from loop_symphony.manager.room_registry import (
    RoomInfo,
    RoomRegistry,
    RoomRegistration,
)
from loop_symphony.models.finding import ExecutionMetadata, Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskRequest, TaskResponse


def _make_registry_with_rooms() -> RoomRegistry:
    """Create a RoomRegistry with server + local room."""
    registry = RoomRegistry()
    registry.register_server(
        capabilities={"reasoning", "synthesis", "analysis", "web_search"},
        instruments=["note", "research", "synthesis"],
    )
    registry.register(RoomRegistration(
        room_id="local-1",
        room_name="Local Room",
        room_type="local",
        url="http://localhost:8001",
        capabilities=["reasoning"],
        instruments=["local_note"],
    ))
    return registry


def _mock_note_instrument(summary: str = "Server result") -> MagicMock:
    """Create a mock note instrument."""
    mock = MagicMock()
    mock.required_capabilities = frozenset({"reasoning"})
    mock.execute = AsyncMock(return_value=InstrumentResult(
        outcome=Outcome.COMPLETE,
        findings=[Finding(content=summary)],
        summary=summary,
        confidence=0.85,
        iterations=1,
    ))
    return mock


class TestOfflineRoomFallback:
    """Tests for fallback when rooms go offline."""

    @pytest.mark.asyncio
    async def test_offline_room_falls_back_to_server(self):
        """When local room is offline, fall back to server execution."""
        registry = _make_registry_with_rooms()
        # Mark local room offline
        room = registry.get_room("local-1")
        room.status = "offline"

        conductor = Conductor(room_registry=registry)
        conductor.instruments["note"] = _mock_note_instrument("Server fallback")

        # Privacy query that would normally go to local
        request = TaskRequest(query="My doctor prescribed medication")
        response = await conductor.execute(request)

        # Should execute on server since local is offline
        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Server fallback"
        assert response.metadata.room_id == "server"

    @pytest.mark.asyncio
    async def test_all_rooms_offline_server_only(self):
        """When all remote rooms offline, server handles everything."""
        registry = _make_registry_with_rooms()
        # Mark local room offline
        room = registry.get_room("local-1")
        room.status = "offline"

        conductor = Conductor(room_registry=registry)
        conductor.instruments["note"] = _mock_note_instrument("Only server left")

        request = TaskRequest(query="Any question here")
        response = await conductor.execute(request)

        assert response.outcome == Outcome.COMPLETE
        assert response.metadata.room_id == "server"

    @pytest.mark.asyncio
    async def test_delegation_timeout_falls_back_to_server(self):
        """When delegation times out, fall back to server."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)
        conductor.instruments["note"] = _mock_note_instrument("Timeout fallback")

        mock_result = RoomDelegationResult(
            success=False,
            error="Timeout after 60000ms",
            room_id="local-1",
            latency_ms=60000,
        )

        with patch.object(
            RoomClient, "delegate", new_callable=AsyncMock, return_value=mock_result
        ):
            request = TaskRequest(query="My SSN is 123-45-6789")
            response = await conductor.execute(request)

        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Timeout fallback"
        assert len(response.metadata.failover_events) == 1


class TestFailoverMetadata:
    """Tests for failover event tracking in metadata."""

    @pytest.mark.asyncio
    async def test_failover_event_logged(self):
        """Failover events are recorded in metadata."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)
        conductor.instruments["note"] = _mock_note_instrument()

        mock_result = RoomDelegationResult(
            success=False,
            error="Connection refused",
            room_id="local-1",
            latency_ms=50,
        )

        with patch.object(
            RoomClient, "delegate", new_callable=AsyncMock, return_value=mock_result
        ):
            request = TaskRequest(query="My doctor said I need medication")
            response = await conductor.execute(request)

        events = response.metadata.failover_events
        assert len(events) == 1
        assert events[0]["original_room_id"] == "local-1"
        assert events[0]["fallback_room_id"] == "server"
        assert events[0]["reason"] == "delegation_failed"

    @pytest.mark.asyncio
    async def test_no_failover_on_success(self):
        """No failover events when delegation succeeds."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        mock_response = TaskResponse(
            request_id="test-id",
            outcome=Outcome.COMPLETE,
            findings=[],
            summary="Remote success",
            confidence=0.9,
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
        assert response.metadata.room_id == "local-1"

    @pytest.mark.asyncio
    async def test_response_includes_room_id_for_direct_execution(self):
        """Server execution includes room_id='server' in metadata."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)
        conductor.instruments["note"] = _mock_note_instrument()

        request = TaskRequest(query="What is the capital of France?")
        response = await conductor.execute(request)

        assert response.metadata.room_id == "server"
        assert response.metadata.failover_events == []


class TestDegradationStatus:
    """Tests for the degradation status endpoint."""

    def test_degradation_status_all_online(self):
        registry = _make_registry_with_rooms()
        status = registry.get_degradation_status()

        assert status["fully_operational"] is True
        assert "server" in status["online_rooms"]
        assert "local-1" in status["online_rooms"]
        assert len(status["offline_rooms"]) == 0
        assert len(status["degraded_rooms"]) == 0

    def test_degradation_status_mixed(self):
        registry = _make_registry_with_rooms()
        room = registry.get_room("local-1")
        room.status = "degraded"

        status = registry.get_degradation_status()

        assert status["fully_operational"] is False
        assert "local-1" in status["degraded_rooms"]
        assert "server" in status["online_rooms"]
        assert "reasoning" in status["capabilities_degraded"]

    def test_degradation_status_all_offline(self):
        registry = _make_registry_with_rooms()
        room = registry.get_room("local-1")
        room.status = "offline"

        status = registry.get_degradation_status()

        assert status["fully_operational"] is False
        assert "local-1" in status["offline_rooms"]
        # Server is still online
        assert "server" in status["online_rooms"]

    def test_capabilities_available_reflects_online_rooms(self):
        registry = _make_registry_with_rooms()
        status = registry.get_degradation_status()

        # Both rooms online
        assert "reasoning" in status["capabilities_available"]
        assert "web_search" in status["capabilities_available"]

        # Take local offline — reasoning still available from server
        room = registry.get_room("local-1")
        room.status = "offline"

        status = registry.get_degradation_status()
        assert "reasoning" in status["capabilities_available"]  # Server still has it


class TestExecutionMetadataFields:
    """Tests for new ExecutionMetadata fields."""

    def test_room_id_default_none(self):
        meta = ExecutionMetadata(
            instrument_used="note",
            iterations=1,
            duration_ms=100,
        )
        assert meta.room_id is None
        assert meta.failover_events == []

    def test_room_id_set(self):
        meta = ExecutionMetadata(
            instrument_used="note",
            iterations=1,
            duration_ms=100,
            room_id="local-1",
        )
        assert meta.room_id == "local-1"

    def test_failover_events_populated(self):
        meta = ExecutionMetadata(
            instrument_used="note",
            iterations=1,
            duration_ms=100,
            failover_events=[
                {"original_room_id": "local-1", "fallback_room_id": "server"},
            ],
        )
        assert len(meta.failover_events) == 1
        assert meta.failover_events[0]["original_room_id"] == "local-1"

    def test_backward_compatible_serialization(self):
        """Old metadata without room fields still works."""
        meta = ExecutionMetadata(
            instrument_used="note",
            iterations=1,
            duration_ms=100,
        )
        d = meta.model_dump()
        assert "room_id" in d
        assert d["room_id"] is None
        assert "failover_events" in d
        assert d["failover_events"] == []
