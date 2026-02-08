"""HTTP client for delegating tasks to remote rooms (Phase 4C).

Handles HTTP POST delegation to remote rooms (Local, iOS) and
normalizes their responses back into the server's TaskResponse format.
"""

from __future__ import annotations

import logging
import time

import httpx
from pydantic import BaseModel, Field

from loop_symphony.manager.room_registry import RoomInfo
from loop_symphony.models.finding import ExecutionMetadata, Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskRequest, TaskResponse

logger = logging.getLogger(__name__)


class RoomDelegationResult(BaseModel):
    """Result from delegating a task to a remote room."""

    success: bool
    response: TaskResponse | None = None
    error: str | None = None
    room_id: str
    latency_ms: int = 0


class RoomClient:
    """HTTP client for delegating tasks to remote rooms.

    Sends tasks to remote rooms via their /task endpoint and
    normalizes the response into the server's TaskResponse format.
    """

    def __init__(
        self,
        timeout: float = 60.0,
    ) -> None:
        """Initialize the room client.

        Args:
            timeout: Request timeout in seconds
        """
        self._timeout = timeout

    async def delegate(
        self,
        room: RoomInfo,
        request: TaskRequest,
    ) -> RoomDelegationResult:
        """Delegate a task to a remote room via HTTP POST.

        Args:
            room: The target room
            request: The task request to delegate

        Returns:
            RoomDelegationResult with success/failure and normalized response
        """
        start_time = time.time()

        payload = {
            "query": request.query,
            "instrument": "local_note",  # Remote rooms currently support local_note
        }
        if request.context:
            payload["context"] = request.context.model_dump(
                exclude={"checkpoint_fn", "spawn_fn"},
                exclude_none=True,
            )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{room.url}/task",
                    json=payload,
                )

            latency_ms = int((time.time() - start_time) * 1000)

            if resp.status_code != 200:
                return RoomDelegationResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    room_id=room.room_id,
                    latency_ms=latency_ms,
                )

            raw = resp.json()
            normalized = self._normalize_response(
                raw=raw,
                request_id=str(request.id),
                room=room,
                latency_ms=latency_ms,
            )

            return RoomDelegationResult(
                success=True,
                response=normalized,
                room_id=room.room_id,
                latency_ms=latency_ms,
            )

        except httpx.TimeoutException:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning(f"Timeout delegating to room {room.room_id} after {latency_ms}ms")
            return RoomDelegationResult(
                success=False,
                error=f"Timeout after {latency_ms}ms",
                room_id=room.room_id,
                latency_ms=latency_ms,
            )

        except httpx.ConnectError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning(f"Connection error delegating to room {room.room_id}: {e}")
            return RoomDelegationResult(
                success=False,
                error=f"Connection error: {e}",
                room_id=room.room_id,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Unexpected error delegating to room {room.room_id}: {e}")
            return RoomDelegationResult(
                success=False,
                error=f"Unexpected error: {e}",
                room_id=room.room_id,
                latency_ms=latency_ms,
            )

    async def check_health(self, room: RoomInfo) -> bool:
        """Quick health check on a remote room.

        Args:
            room: The room to check

        Returns:
            True if room is healthy
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{room.url}/health")
            return resp.status_code == 200
        except Exception:
            return False

    def _normalize_response(
        self,
        raw: dict,
        request_id: str,
        room: RoomInfo,
        latency_ms: int,
    ) -> TaskResponse:
        """Convert a remote room's response to server TaskResponse format.

        The local room returns a flat structure:
            {"outcome": "COMPLETE", "findings": [...], "summary": "...",
             "confidence": 0.85, "instrument": "local_note", "room_id": "..."}

        We normalize this to the server's TaskResponse with proper
        Outcome enum, Finding objects, and ExecutionMetadata.
        """
        # Map outcome string to Outcome enum (local room uses uppercase)
        outcome_str = raw.get("outcome", "INCONCLUSIVE").lower()
        try:
            outcome = Outcome(outcome_str)
        except ValueError:
            outcome = Outcome.INCONCLUSIVE

        # Convert raw findings dicts to Finding objects
        findings = []
        for f in raw.get("findings", []):
            if isinstance(f, dict):
                findings.append(Finding(
                    content=f.get("content", ""),
                    source=f.get("source"),
                    confidence=f.get("confidence", 0.5),
                ))
            elif isinstance(f, str):
                findings.append(Finding(content=f))

        instrument = raw.get("instrument", "unknown")
        room_id = raw.get("room_id", room.room_id)

        return TaskResponse(
            request_id=request_id,
            outcome=outcome,
            findings=findings,
            summary=raw.get("summary", ""),
            confidence=raw.get("confidence", 0.0),
            metadata=ExecutionMetadata(
                instrument_used=f"room:{room_id}/{instrument}",
                iterations=raw.get("iterations", 1),
                duration_ms=latency_ms,
                sources_consulted=[f"room:{room_id}"],
                process_type=ProcessType.SEMI_AUTONOMIC,
                room_id=room_id,
            ),
        )
