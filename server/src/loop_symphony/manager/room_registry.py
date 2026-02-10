"""Room registry for multi-room architecture (Phase 4).

Tracks connected rooms (Local, iOS, etc.) and their capabilities.
Used for routing tasks to the appropriate room.
"""

import logging
from datetime import datetime, timedelta, UTC
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RoomInfo(BaseModel):
    """Information about a connected room."""

    room_id: str
    room_name: str
    room_type: str  # "local", "ios", "server"
    url: str  # How to reach this room
    capabilities: set[str] = Field(default_factory=set)
    instruments: list[str] = Field(default_factory=list)
    status: str = "online"  # online, offline, degraded
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(UTC))
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoomRegistration(BaseModel):
    """Registration request from a room."""

    room_id: str
    room_name: str
    room_type: str = "local"
    url: str
    capabilities: list[str]
    instruments: list[str]


class RoomHeartbeat(BaseModel):
    """Heartbeat from a room."""

    room_id: str
    status: str = "online"
    capabilities: list[str] | None = None
    last_knowledge_version: int | None = None


class RoomRegistry:
    """Registry of connected rooms.

    Tracks rooms, their capabilities, and health status.
    Used for routing decisions.
    """

    def __init__(self, heartbeat_timeout: int = 120) -> None:
        """Initialize the registry.

        Args:
            heartbeat_timeout: Seconds before a room is considered offline
        """
        self._rooms: dict[str, RoomInfo] = {}
        self._heartbeat_timeout = heartbeat_timeout

    def register(self, registration: RoomRegistration) -> RoomInfo:
        """Register a new room or update existing.

        Args:
            registration: Room registration info

        Returns:
            The registered RoomInfo
        """
        room = RoomInfo(
            room_id=registration.room_id,
            room_name=registration.room_name,
            room_type=registration.room_type,
            url=registration.url,
            capabilities=set(registration.capabilities),
            instruments=registration.instruments,
            status="online",
        )

        self._rooms[registration.room_id] = room
        logger.info(
            f"Room registered: {registration.room_id} "
            f"({registration.room_type}) at {registration.url}"
        )
        return room

    def deregister(self, room_id: str) -> bool:
        """Remove a room from the registry.

        Args:
            room_id: Room to remove

        Returns:
            True if room was found and removed
        """
        if room_id in self._rooms:
            del self._rooms[room_id]
            logger.info(f"Room deregistered: {room_id}")
            return True
        return False

    def heartbeat(self, heartbeat: RoomHeartbeat) -> bool:
        """Process a heartbeat from a room.

        Args:
            heartbeat: Heartbeat info

        Returns:
            True if room exists
        """
        room = self._rooms.get(heartbeat.room_id)
        if not room:
            return False

        room.last_heartbeat = datetime.now(UTC)
        room.status = heartbeat.status

        if heartbeat.capabilities is not None:
            room.capabilities = set(heartbeat.capabilities)

        return True

    def get_room(self, room_id: str) -> RoomInfo | None:
        """Get a room by ID."""
        return self._rooms.get(room_id)

    def get_all_rooms(self) -> list[RoomInfo]:
        """Get all registered rooms."""
        self._check_timeouts()
        return list(self._rooms.values())

    def get_online_rooms(self) -> list[RoomInfo]:
        """Get all online rooms."""
        self._check_timeouts()
        return [r for r in self._rooms.values() if r.status == "online"]

    def get_rooms_by_capability(self, capability: str) -> list[RoomInfo]:
        """Get rooms that have a specific capability.

        Args:
            capability: The capability to look for

        Returns:
            List of rooms with that capability
        """
        self._check_timeouts()
        return [
            r for r in self._rooms.values()
            if r.status == "online" and capability in r.capabilities
        ]

    def get_rooms_by_instrument(self, instrument: str) -> list[RoomInfo]:
        """Get rooms that have a specific instrument.

        Args:
            instrument: The instrument to look for

        Returns:
            List of rooms with that instrument
        """
        self._check_timeouts()
        return [
            r for r in self._rooms.values()
            if r.status == "online" and instrument in r.instruments
        ]

    def get_best_room_for_task(
        self,
        required_capabilities: set[str] | None = None,
        preferred_room_type: str | None = None,
        prefer_local: bool = False,
    ) -> RoomInfo | None:
        """Select the best room for a task.

        Args:
            required_capabilities: Capabilities the room must have
            preferred_room_type: Preferred room type (local, server, etc.)
            prefer_local: If True, prefer local rooms over server

        Returns:
            The best matching room, or None if none found
        """
        self._check_timeouts()
        candidates = [r for r in self._rooms.values() if r.status == "online"]

        if not candidates:
            return None

        # Filter by required capabilities
        if required_capabilities:
            candidates = [
                r for r in candidates
                if required_capabilities.issubset(r.capabilities)
            ]

        if not candidates:
            return None

        # Sort by preference
        def score(room: RoomInfo) -> int:
            s = 0
            if preferred_room_type and room.room_type == preferred_room_type:
                s += 10
            if prefer_local and room.room_type == "local":
                s += 5
            # Prefer rooms with more capabilities as tiebreaker
            s += len(room.capabilities)
            return s

        candidates.sort(key=score, reverse=True)
        return candidates[0]

    def register_server(
        self,
        capabilities: set[str],
        instruments: list[str],
    ) -> RoomInfo:
        """Register the server room (implicit, always online).

        The server room is special: it never times out and represents
        the local execution environment. This lets the scoring logic
        compare server vs remote rooms on equal footing.

        Args:
            capabilities: Server's capabilities
            instruments: Server's available instruments

        Returns:
            The registered server RoomInfo
        """
        server_room = RoomInfo(
            room_id="server",
            room_name="Server Room",
            room_type="server",
            url="local",  # Sentinel — never used for HTTP
            capabilities=capabilities,
            instruments=instruments,
            status="online",
        )
        self._rooms["server"] = server_room
        logger.info(
            f"Server room registered with capabilities: {capabilities}"
        )
        return server_room

    def get_degradation_status(self) -> dict:
        """Get degradation status for all rooms.

        Returns:
            Dict with online/offline/degraded room lists and capability info
        """
        self._check_timeouts()
        rooms = list(self._rooms.values())

        online = [r for r in rooms if r.status == "online"]
        offline = [r for r in rooms if r.status == "offline"]
        degraded = [r for r in rooms if r.status == "degraded"]

        caps_available: set[str] = set()
        for r in online:
            caps_available.update(r.capabilities)

        caps_degraded: set[str] = set()
        for r in degraded:
            caps_degraded.update(r.capabilities)

        return {
            "fully_operational": len(offline) == 0 and len(degraded) == 0,
            "online_rooms": [r.room_id for r in online],
            "offline_rooms": [r.room_id for r in offline],
            "degraded_rooms": [r.room_id for r in degraded],
            "capabilities_available": sorted(caps_available),
            "capabilities_degraded": sorted(caps_degraded),
        }

    def _check_timeouts(self) -> None:
        """Mark rooms as offline if heartbeat timed out."""
        cutoff = datetime.now(UTC) - timedelta(seconds=self._heartbeat_timeout)

        for room in self._rooms.values():
            if room.status == "online" and room.last_heartbeat < cutoff:
                room.status = "offline"
                logger.warning(f"Room timed out: {room.room_id}")

    def stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        self._check_timeouts()
        rooms = list(self._rooms.values())

        return {
            "total_rooms": len(rooms),
            "online_rooms": sum(1 for r in rooms if r.status == "online"),
            "offline_rooms": sum(1 for r in rooms if r.status == "offline"),
            "rooms_by_type": {
                t: sum(1 for r in rooms if r.room_type == t)
                for t in set(r.room_type for r in rooms)
            },
        }
