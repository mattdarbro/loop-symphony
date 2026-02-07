"""Local Room registration and lifecycle management.

Handles registration with the main Loop Symphony server and
maintains heartbeat/presence.
"""

import asyncio
import logging
from datetime import datetime, UTC
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from local_room.config import LocalRoomConfig
from local_room.tools.ollama import OllamaClient
from local_room.instruments.note import LocalNoteInstrument
from local_room.router import TaskRouter, RoutingDecision, RoutingResult
from local_room.privacy import PrivacyClassifier

logger = logging.getLogger(__name__)


class RoomInfo(BaseModel):
    """Information about a room."""

    room_id: str
    room_name: str
    room_type: str = "local"
    url: str  # How to reach this room
    capabilities: set[str] = Field(default_factory=set)
    instruments: list[str] = Field(default_factory=list)
    status: str = "online"  # online, offline, degraded
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoomRegistration(BaseModel):
    """Registration request to send to server."""

    room_id: str
    room_name: str
    room_type: str = "local"
    url: str
    capabilities: list[str]
    instruments: list[str]


class LocalRoom:
    """The Local Room service.

    Manages:
    - Registration with Loop Symphony server
    - Heartbeat/presence
    - Local instrument execution
    - Privacy-aware routing
    - Offline fallback
    """

    def __init__(self, config: LocalRoomConfig) -> None:
        """Initialize the Local Room.

        Args:
            config: Room configuration
        """
        self._config = config
        self._ollama = OllamaClient(
            host=config.ollama_host,
            model=config.ollama_model,
            timeout=config.ollama_timeout,
        )
        self._note = LocalNoteInstrument(self._ollama)
        self._router = TaskRouter(
            server_url=config.server_url,
            local_capabilities=config.capabilities,
        )
        self._privacy_classifier = PrivacyClassifier()
        self._registered = False
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def info(self) -> RoomInfo:
        """Get current room info."""
        return RoomInfo(
            room_id=self._config.room_id,
            room_name=self._config.room_name,
            room_type="local",
            url=f"http://{self._config.host}:{self._config.port}",
            capabilities=self._config.capabilities,
            instruments=["local_note"],
            status="online" if self._registered else "offline",
        )

    @property
    def ollama(self) -> OllamaClient:
        """Get the Ollama client."""
        return self._ollama

    @property
    def note_instrument(self) -> LocalNoteInstrument:
        """Get the Note instrument."""
        return self._note

    @property
    def router(self) -> TaskRouter:
        """Get the task router."""
        return self._router

    @property
    def privacy_classifier(self) -> PrivacyClassifier:
        """Get the privacy classifier."""
        return self._privacy_classifier

    async def route_task(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        force_local: bool = False,
    ) -> RoutingResult:
        """Route a task to the appropriate destination.

        Args:
            query: The query to route
            context: Optional context
            force_local: Force local execution

        Returns:
            RoutingResult with decision
        """
        return await self._router.route(query, context, force_local=force_local)

    async def start(self) -> None:
        """Start the room (register and begin heartbeat)."""
        # Check Ollama health first
        health = await self._ollama.health_check()
        if not health.get("healthy"):
            logger.warning(f"Ollama not healthy: {health.get('error')}")
            # Continue anyway - might come online later

        # Start router (begins server health checks)
        await self._router.start()

        # Register with server
        await self._register()

        # Start heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Local Room started: {self._config.room_id}")

    async def stop(self) -> None:
        """Stop the room (deregister and stop heartbeat)."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        await self._router.stop()
        await self._deregister()
        logger.info(f"Local Room stopped: {self._config.room_id}")

    async def _register(self) -> bool:
        """Register with the Loop Symphony server."""
        registration = RoomRegistration(
            room_id=self._config.room_id,
            room_name=self._config.room_name,
            room_type="local",
            url=f"http://{self._config.host}:{self._config.port}",
            capabilities=list(self._config.capabilities),
            instruments=["local_note"],
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._config.server_url}/rooms/register",
                    json=registration.model_dump(),
                )

                if response.status_code == 200:
                    self._registered = True
                    logger.info(f"Registered with server: {self._config.server_url}")
                    return True
                else:
                    logger.warning(
                        f"Registration failed: {response.status_code} - {response.text}"
                    )
                    return False

        except httpx.ConnectError:
            logger.warning(f"Cannot connect to server: {self._config.server_url}")
            return False
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False

    async def _deregister(self) -> bool:
        """Deregister from the server."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._config.server_url}/rooms/deregister",
                    json={"room_id": self._config.room_id},
                )
                self._registered = False
                return response.status_code == 200

        except Exception as e:
            logger.error(f"Deregistration error: {e}")
            self._registered = False
            return False

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to the server."""
        while True:
            try:
                await asyncio.sleep(self._config.registration_interval)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _send_heartbeat(self) -> bool:
        """Send a heartbeat to the server."""
        # Get current health status
        ollama_health = await self._ollama.health_check()
        status = "online" if ollama_health.get("healthy") else "degraded"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._config.server_url}/rooms/heartbeat",
                    json={
                        "room_id": self._config.room_id,
                        "status": status,
                        "capabilities": list(self._config.capabilities),
                    },
                )

                if response.status_code == 200:
                    self._registered = True
                    return True
                elif response.status_code == 404:
                    # Room not found - re-register
                    logger.info("Room not found, re-registering...")
                    return await self._register()
                else:
                    return False

        except httpx.ConnectError:
            logger.debug("Server unreachable for heartbeat")
            return False
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            return False

    async def health_check(self) -> dict[str, Any]:
        """Get overall health status."""
        ollama_health = await self._ollama.health_check()
        note_health = await self._note.health_check()
        router_status = self._router.get_status()

        return {
            "healthy": ollama_health.get("healthy", False),
            "room_id": self._config.room_id,
            "registered": self._registered,
            "server_available": router_status.get("server_available", False),
            "ollama": ollama_health,
            "router": router_status,
            "instruments": {
                "local_note": note_health,
            },
        }
