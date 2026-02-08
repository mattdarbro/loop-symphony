"""Tests for RoomClient remote delegation (Phase 4C)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from loop_symphony.manager.room_client import RoomClient, RoomDelegationResult
from loop_symphony.manager.room_registry import RoomInfo
from loop_symphony.models.finding import ExecutionMetadata
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskRequest, TaskResponse


def _make_room(room_id: str = "local-1", url: str = "http://localhost:8001") -> RoomInfo:
    return RoomInfo(
        room_id=room_id,
        room_name="Local Room",
        room_type="local",
        url=url,
        capabilities={"reasoning"},
        instruments=["local_note"],
    )


def _make_request(query: str = "Hello world") -> TaskRequest:
    return TaskRequest(query=query)


def _make_room_response(
    outcome: str = "COMPLETE",
    summary: str = "Test summary",
    confidence: float = 0.85,
) -> dict:
    """Build a response dict as returned by a local room's /task endpoint."""
    return {
        "outcome": outcome,
        "findings": [
            {"content": "Finding 1", "source": "local", "confidence": 0.9},
            {"content": "Finding 2", "confidence": 0.7},
        ],
        "summary": summary,
        "confidence": confidence,
        "iterations": 1,
        "duration_ms": 150,
        "instrument": "local_note",
        "room_id": "local-1",
    }


class TestRoomDelegationResult:
    """Tests for RoomDelegationResult model."""

    def test_success_result(self):
        result = RoomDelegationResult(
            success=True,
            room_id="local-1",
            latency_ms=100,
        )
        assert result.success is True
        assert result.response is None
        assert result.error is None

    def test_failure_result(self):
        result = RoomDelegationResult(
            success=False,
            error="Connection refused",
            room_id="local-1",
            latency_ms=50,
        )
        assert result.success is False
        assert result.error == "Connection refused"


class TestRoomClientDelegate:
    """Tests for RoomClient.delegate()."""

    @pytest.mark.asyncio
    async def test_delegate_success(self):
        client = RoomClient()
        room = _make_room()
        request = _make_request()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_room_response()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await client.delegate(room, request)

        assert result.success is True
        assert result.response is not None
        assert result.response.outcome == Outcome.COMPLETE
        assert result.response.confidence == 0.85
        assert result.room_id == "local-1"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_delegate_http_error(self):
        client = RoomClient()
        room = _make_room()
        request = _make_request()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await client.delegate(room, request)

        assert result.success is False
        assert "500" in result.error
        assert result.response is None

    @pytest.mark.asyncio
    async def test_delegate_timeout(self):
        client = RoomClient(timeout=1.0)
        room = _make_room()
        request = _make_request()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await client.delegate(room, request)

        assert result.success is False
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_delegate_connection_error(self):
        client = RoomClient()
        room = _make_room()
        request = _make_request()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await client.delegate(room, request)

        assert result.success is False
        assert "Connection error" in result.error

    @pytest.mark.asyncio
    async def test_delegate_unexpected_error(self):
        client = RoomClient()
        room = _make_room()
        request = _make_request()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = RuntimeError("something broke")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await client.delegate(room, request)

        assert result.success is False
        assert "Unexpected error" in result.error


class TestRoomClientNormalization:
    """Tests for response normalization."""

    def test_normalize_complete_response(self):
        client = RoomClient()
        room = _make_room()
        raw = _make_room_response(outcome="COMPLETE", confidence=0.9)

        result = client._normalize_response(raw, "req-1", room, 100)

        assert isinstance(result, TaskResponse)
        assert result.outcome == Outcome.COMPLETE
        assert result.confidence == 0.9
        assert len(result.findings) == 2
        assert result.findings[0].content == "Finding 1"
        assert result.findings[0].confidence == 0.9
        assert result.findings[1].content == "Finding 2"

    def test_normalize_bounded_response(self):
        client = RoomClient()
        room = _make_room()
        raw = _make_room_response(outcome="BOUNDED")

        result = client._normalize_response(raw, "req-1", room, 100)
        assert result.outcome == Outcome.BOUNDED

    def test_normalize_inconclusive_response(self):
        client = RoomClient()
        room = _make_room()
        raw = _make_room_response(outcome="INCONCLUSIVE")

        result = client._normalize_response(raw, "req-1", room, 100)
        assert result.outcome == Outcome.INCONCLUSIVE

    def test_normalize_unknown_outcome_defaults_to_inconclusive(self):
        client = RoomClient()
        room = _make_room()
        raw = _make_room_response(outcome="UNKNOWN_STATE")

        result = client._normalize_response(raw, "req-1", room, 100)
        assert result.outcome == Outcome.INCONCLUSIVE

    def test_normalize_metadata(self):
        client = RoomClient()
        room = _make_room()
        raw = _make_room_response()

        result = client._normalize_response(raw, "req-1", room, 150)

        assert result.metadata.instrument_used == "room:local-1/local_note"
        assert result.metadata.iterations == 1
        assert result.metadata.duration_ms == 150
        assert "room:local-1" in result.metadata.sources_consulted
        assert result.metadata.process_type == ProcessType.SEMI_AUTONOMIC
        assert result.metadata.room_id == "local-1"

    def test_normalize_missing_fields_uses_defaults(self):
        client = RoomClient()
        room = _make_room()
        raw = {}  # Minimal response

        result = client._normalize_response(raw, "req-1", room, 50)

        assert result.outcome == Outcome.INCONCLUSIVE
        assert result.confidence == 0.0
        assert result.summary == ""
        assert result.findings == []

    def test_normalize_string_findings(self):
        client = RoomClient()
        room = _make_room()
        raw = {
            "outcome": "COMPLETE",
            "findings": ["Simple string finding"],
            "summary": "Done",
            "confidence": 0.8,
        }

        result = client._normalize_response(raw, "req-1", room, 50)
        assert len(result.findings) == 1
        assert result.findings[0].content == "Simple string finding"


class TestRoomClientHealthCheck:
    """Tests for RoomClient.check_health()."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        client = RoomClient()
        room = _make_room()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await client.check_health(room)

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        client = RoomClient()
        room = _make_room()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await client.check_health(room)

        assert result is False
