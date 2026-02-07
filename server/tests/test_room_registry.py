"""Tests for room registry (Phase 4)."""

import pytest
from datetime import datetime, timedelta, UTC

from loop_symphony.manager.room_registry import (
    RoomRegistry,
    RoomRegistration,
    RoomHeartbeat,
    RoomInfo,
)


class TestRoomInfo:
    """Tests for RoomInfo model."""

    def test_basic_info(self):
        info = RoomInfo(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
        )
        assert info.room_id == "local-1"
        assert info.status == "online"

    def test_with_capabilities(self):
        info = RoomInfo(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities={"reasoning", "synthesis"},
            instruments=["local_note"],
        )
        assert "reasoning" in info.capabilities
        assert "local_note" in info.instruments


class TestRoomRegistration:
    """Tests for RoomRegistration model."""

    def test_registration(self):
        reg = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        assert reg.room_type == "local"


class TestRoomRegistry:
    """Tests for RoomRegistry."""

    def test_register(self):
        registry = RoomRegistry()
        reg = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )

        room = registry.register(reg)

        assert room.room_id == "local-1"
        assert room.status == "online"
        assert "reasoning" in room.capabilities

    def test_deregister(self):
        registry = RoomRegistry()
        reg = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg)

        result = registry.deregister("local-1")
        assert result is True

        result = registry.deregister("local-1")
        assert result is False  # Already removed

    def test_heartbeat(self):
        registry = RoomRegistry()
        reg = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg)

        heartbeat = RoomHeartbeat(
            room_id="local-1",
            status="online",
        )
        result = registry.heartbeat(heartbeat)
        assert result is True

    def test_heartbeat_unknown_room(self):
        registry = RoomRegistry()

        heartbeat = RoomHeartbeat(
            room_id="unknown",
            status="online",
        )
        result = registry.heartbeat(heartbeat)
        assert result is False

    def test_heartbeat_updates_capabilities(self):
        registry = RoomRegistry()
        reg = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg)

        heartbeat = RoomHeartbeat(
            room_id="local-1",
            status="online",
            capabilities=["reasoning", "synthesis"],
        )
        registry.heartbeat(heartbeat)

        room = registry.get_room("local-1")
        assert "synthesis" in room.capabilities

    def test_get_room(self):
        registry = RoomRegistry()
        reg = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg)

        room = registry.get_room("local-1")
        assert room is not None
        assert room.room_id == "local-1"

        room = registry.get_room("unknown")
        assert room is None

    def test_get_all_rooms(self):
        registry = RoomRegistry()

        for i in range(3):
            reg = RoomRegistration(
                room_id=f"local-{i}",
                room_name=f"Local Room {i}",
                room_type="local",
                url=f"http://localhost:800{i}",
                capabilities=["reasoning"],
                instruments=["local_note"],
            )
            registry.register(reg)

        rooms = registry.get_all_rooms()
        assert len(rooms) == 3

    def test_get_online_rooms(self):
        registry = RoomRegistry()

        reg1 = RoomRegistration(
            room_id="local-1",
            room_name="Local Room 1",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg1)

        reg2 = RoomRegistration(
            room_id="local-2",
            room_name="Local Room 2",
            room_type="local",
            url="http://localhost:8002",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg2)

        # Mark one as degraded
        registry.heartbeat(RoomHeartbeat(room_id="local-2", status="degraded"))

        online = registry.get_online_rooms()
        assert len(online) == 1
        assert online[0].room_id == "local-1"

    def test_get_rooms_by_capability(self):
        registry = RoomRegistry()

        reg1 = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg1)

        reg2 = RoomRegistration(
            room_id="server",
            room_name="Server Room",
            room_type="server",
            url="http://server:8000",
            capabilities=["reasoning", "web_search"],
            instruments=["research"],
        )
        registry.register(reg2)

        reasoning_rooms = registry.get_rooms_by_capability("reasoning")
        assert len(reasoning_rooms) == 2

        search_rooms = registry.get_rooms_by_capability("web_search")
        assert len(search_rooms) == 1
        assert search_rooms[0].room_id == "server"

    def test_get_rooms_by_instrument(self):
        registry = RoomRegistry()

        reg1 = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg1)

        reg2 = RoomRegistration(
            room_id="server",
            room_name="Server Room",
            room_type="server",
            url="http://server:8000",
            capabilities=["reasoning"],
            instruments=["note", "research"],
        )
        registry.register(reg2)

        note_rooms = registry.get_rooms_by_instrument("local_note")
        assert len(note_rooms) == 1

        research_rooms = registry.get_rooms_by_instrument("research")
        assert len(research_rooms) == 1

    def test_get_best_room_for_task(self):
        registry = RoomRegistry()

        reg1 = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg1)

        reg2 = RoomRegistration(
            room_id="server",
            room_name="Server Room",
            room_type="server",
            url="http://server:8000",
            capabilities=["reasoning", "web_search"],
            instruments=["research"],
        )
        registry.register(reg2)

        # Prefer local
        best = registry.get_best_room_for_task(prefer_local=True)
        assert best.room_id == "local-1"

        # Need web_search
        best = registry.get_best_room_for_task(
            required_capabilities={"web_search"}
        )
        assert best.room_id == "server"

        # No room has this capability
        best = registry.get_best_room_for_task(
            required_capabilities={"video_processing"}
        )
        assert best is None

    def test_timeout_detection(self):
        registry = RoomRegistry(heartbeat_timeout=60)

        reg = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        room = registry.register(reg)

        # Simulate old heartbeat
        room.last_heartbeat = datetime.now(UTC) - timedelta(seconds=120)

        # Check should mark as offline
        online = registry.get_online_rooms()
        assert len(online) == 0

        room = registry.get_room("local-1")
        assert room.status == "offline"

    def test_stats(self):
        registry = RoomRegistry()

        reg1 = RoomRegistration(
            room_id="local-1",
            room_name="Local Room",
            room_type="local",
            url="http://localhost:8001",
            capabilities=["reasoning"],
            instruments=["local_note"],
        )
        registry.register(reg1)

        reg2 = RoomRegistration(
            room_id="server",
            room_name="Server Room",
            room_type="server",
            url="http://server:8000",
            capabilities=["reasoning"],
            instruments=["research"],
        )
        registry.register(reg2)

        stats = registry.stats()
        assert stats["total_rooms"] == 2
        assert stats["online_rooms"] == 2
        assert stats["rooms_by_type"]["local"] == 1
        assert stats["rooms_by_type"]["server"] == 1
