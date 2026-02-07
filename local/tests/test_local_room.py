"""Tests for Local Room (Phase 4A)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from local_room.config import LocalRoomConfig
from local_room.tools.base import Tool, ToolManifest
from local_room.tools.ollama import OllamaClient, OllamaError
from local_room.instruments.note import LocalNoteInstrument, InstrumentResult
from local_room.room import LocalRoom, RoomInfo, RoomRegistration


class TestLocalRoomConfig:
    """Tests for LocalRoomConfig."""

    def test_defaults(self):
        config = LocalRoomConfig()
        assert config.room_id == "local-room-1"
        assert config.ollama_host == "http://localhost:11434"
        assert config.ollama_model == "llama3.2"
        assert config.port == 8001

    def test_custom_config(self):
        config = LocalRoomConfig(
            room_id="my-room",
            ollama_model="mistral",
            port=9000,
        )
        assert config.room_id == "my-room"
        assert config.ollama_model == "mistral"
        assert config.port == 9000

    def test_capabilities(self):
        config = LocalRoomConfig()
        assert "reasoning" in config.capabilities


class TestToolManifest:
    """Tests for ToolManifest."""

    def test_manifest(self):
        manifest = ToolManifest(
            name="test",
            version="1.0.0",
            description="Test tool",
            capabilities=frozenset({"reasoning"}),
        )
        assert manifest.name == "test"
        assert "reasoning" in manifest.capabilities


class TestOllamaClient:
    """Tests for OllamaClient."""

    def test_init(self):
        client = OllamaClient(
            host="http://localhost:11434",
            model="llama3.2",
        )
        assert client.name == "ollama"
        assert client.model == "llama3.2"

    def test_manifest(self):
        client = OllamaClient()
        manifest = client.manifest
        assert manifest.name == "ollama"
        assert "reasoning" in manifest.capabilities
        assert "synthesis" in manifest.capabilities

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        client = OllamaClient(host="http://localhost:99999")

        with patch("local_room.tools.ollama.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            health = await client.health_check()
            assert health["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        client = OllamaClient(model="llama3.2")

        with patch("local_room.tools.ollama.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "models": [{"name": "llama3.2:latest"}]
            }

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            health = await client.health_check()
            assert health["healthy"] is True
            assert health["model_available"] is True

    @pytest.mark.asyncio
    async def test_complete_success(self):
        client = OllamaClient()

        with patch("local_room.tools.ollama.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": {"content": "Hello! I'm here to help."}
            }

            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await client.complete("Hello!")
            assert result == "Hello! I'm here to help."

    @pytest.mark.asyncio
    async def test_complete_with_system(self):
        client = OllamaClient()

        with patch("local_room.tools.ollama.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": {"content": "Response"}
            }

            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await client.complete(
                "Hello!",
                system="You are helpful.",
            )

            # Verify system message was included
            call_args = mock_instance.post.call_args
            messages = call_args.kwargs["json"]["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_list_models(self):
        client = OllamaClient()

        with patch("local_room.tools.ollama.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "models": [
                    {"name": "llama3.2:latest"},
                    {"name": "mistral:latest"},
                ]
            }

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            models = await client.list_models()
            assert "llama3.2:latest" in models
            assert "mistral:latest" in models


class TestLocalNoteInstrument:
    """Tests for LocalNoteInstrument."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        mock_ollama = AsyncMock(spec=OllamaClient)
        mock_ollama.complete = AsyncMock(return_value="The answer is 4.")
        mock_ollama.model = "llama3.2"

        instrument = LocalNoteInstrument(mock_ollama)

        result = await instrument.execute("What is 2+2?")

        assert result.outcome == "COMPLETE"
        assert len(result.findings) == 1
        assert result.findings[0].content == "The answer is 4."
        assert result.confidence == 0.85
        assert result.instrument == "local_note"

    @pytest.mark.asyncio
    async def test_execute_with_context(self):
        mock_ollama = AsyncMock(spec=OllamaClient)
        mock_ollama.complete = AsyncMock(return_value="Response")
        mock_ollama.model = "llama3.2"

        instrument = LocalNoteInstrument(mock_ollama)

        result = await instrument.execute(
            "Follow up question",
            context={"conversation_summary": "We discussed math."},
        )

        assert result.outcome == "COMPLETE"
        # Verify context was passed to complete
        call_args = mock_ollama.complete.call_args
        assert "math" in call_args.kwargs.get("system", "")

    @pytest.mark.asyncio
    async def test_execute_ollama_error(self):
        mock_ollama = AsyncMock(spec=OllamaClient)
        mock_ollama.complete = AsyncMock(side_effect=OllamaError("Connection failed"))
        mock_ollama.model = "llama3.2"

        instrument = LocalNoteInstrument(mock_ollama)

        result = await instrument.execute("Test")

        assert result.outcome == "INCONCLUSIVE"
        assert len(result.findings) == 0
        assert "error" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_health_check(self):
        mock_ollama = AsyncMock(spec=OllamaClient)
        mock_ollama.health_check = AsyncMock(return_value={"healthy": True})

        instrument = LocalNoteInstrument(mock_ollama)

        health = await instrument.health_check()
        assert health["healthy"] is True
        assert health["instrument"] == "local_note"


class TestRoomInfo:
    """Tests for RoomInfo model."""

    def test_room_info(self):
        info = RoomInfo(
            room_id="test-room",
            room_name="Test Room",
            url="http://localhost:8001",
            capabilities={"reasoning"},
            instruments=["local_note"],
        )
        assert info.room_id == "test-room"
        assert info.room_type == "local"
        assert info.status == "online"


class TestRoomRegistration:
    """Tests for RoomRegistration model."""

    def test_registration(self):
        reg = RoomRegistration(
            room_id="test-room",
            room_name="Test Room",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        assert reg.room_type == "local"


class TestLocalRoom:
    """Tests for LocalRoom."""

    def test_init(self):
        config = LocalRoomConfig()
        room = LocalRoom(config)
        assert room.info.room_id == config.room_id

    def test_info(self):
        config = LocalRoomConfig(
            room_id="my-room",
            room_name="My Room",
        )
        room = LocalRoom(config)
        info = room.info

        assert info.room_id == "my-room"
        assert info.room_name == "My Room"
        assert "local_note" in info.instruments

    @pytest.mark.asyncio
    async def test_health_check(self):
        config = LocalRoomConfig()
        room = LocalRoom(config)

        with patch.object(room._ollama, "health_check", new_callable=AsyncMock) as mock_health:
            mock_health.return_value = {"healthy": True}

            health = await room.health_check()

            assert "room_id" in health
            assert "ollama" in health
            assert "instruments" in health
