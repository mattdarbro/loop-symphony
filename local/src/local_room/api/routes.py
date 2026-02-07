"""API routes for Local Room.

Exposes endpoints for:
- Health checks
- Task execution (matching server's task format)
- Room info
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from local_room.config import LocalRoomConfig
from local_room.room import LocalRoom

logger = logging.getLogger(__name__)

# Global room instance
_room: LocalRoom | None = None


class TaskRequest(BaseModel):
    """Request to execute a task locally."""

    query: str
    context: dict[str, Any] | None = None
    instrument: str = "local_note"


class TaskResponse(BaseModel):
    """Response from local task execution."""

    outcome: str
    findings: list[dict]
    summary: str
    confidence: float
    iterations: int
    duration_ms: int
    instrument: str
    room_id: str


class HealthResponse(BaseModel):
    """Health check response."""

    healthy: bool
    room_id: str
    registered: bool
    ollama: dict
    instruments: dict


def create_app(config: LocalRoomConfig | None = None) -> FastAPI:
    """Create the FastAPI application.

    Args:
        config: Optional configuration (uses env vars if not provided)

    Returns:
        Configured FastAPI app
    """
    config = config or LocalRoomConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage room lifecycle."""
        global _room
        _room = LocalRoom(config)
        await _room.start()
        yield
        await _room.stop()

    app = FastAPI(
        title="Loop Symphony Local Room",
        description="Edge computing with local LLMs",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health():
        """Check room health."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        health = await _room.health_check()
        return HealthResponse(**health)

    @app.get("/info")
    async def info():
        """Get room info."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        return _room.info.model_dump()

    @app.post("/task", response_model=TaskResponse)
    async def execute_task(request: TaskRequest):
        """Execute a task locally."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        # Currently only support local_note
        if request.instrument != "local_note":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported instrument: {request.instrument}. Only 'local_note' is available.",
            )

        result = await _room.note_instrument.execute(
            query=request.query,
            context=request.context,
        )

        return TaskResponse(
            outcome=result.outcome,
            findings=[f.model_dump() for f in result.findings],
            summary=result.summary,
            confidence=result.confidence,
            iterations=result.iterations,
            duration_ms=result.duration_ms,
            instrument=result.instrument,
            room_id=_room.info.room_id,
        )

    @app.get("/models")
    async def list_models():
        """List available Ollama models."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        models = await _room.ollama.list_models()
        return {"models": models, "current": _room.ollama.model}

    @app.post("/models/pull")
    async def pull_model(model: str):
        """Pull a model from Ollama registry."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        success = await _room.ollama.pull_model(model)
        if success:
            return {"status": "success", "model": model}
        else:
            raise HTTPException(status_code=500, detail=f"Failed to pull model: {model}")

    return app
