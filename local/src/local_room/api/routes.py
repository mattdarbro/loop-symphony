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
from local_room.learning_reporter import LocalLearning
from local_room.room import LocalRoom
from local_room.router import RoutingDecision

logger = logging.getLogger(__name__)

# Global room instance
_room: LocalRoom | None = None


class TaskRequest(BaseModel):
    """Request to execute a task locally."""

    query: str
    context: dict[str, Any] | None = None
    instrument: str = "local_note"
    force_local: bool = False  # Force local execution even if server available


class RouteRequest(BaseModel):
    """Request to route a task."""

    query: str
    context: dict[str, Any] | None = None
    force_local: bool = False
    force_server: bool = False


class PrivacyCheckRequest(BaseModel):
    """Request to check privacy of a query."""

    query: str
    context: dict[str, Any] | None = None


class RecordLearningRequest(BaseModel):
    """Request to manually record a learning."""

    category: str
    title: str
    content: str
    confidence: float = 0.5
    tags: list[str] = Field(default_factory=list)


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

    # =========================================================================
    # Routing & Privacy (Phase 4B)
    # =========================================================================

    @app.post("/route")
    async def route_task(request: RouteRequest):
        """Determine where a task should be routed.

        Returns routing decision: local, server, or escalate.
        """
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        result = await _room.router.route(
            query=request.query,
            context=request.context,
            force_local=request.force_local,
            force_server=request.force_server,
        )

        return {
            "decision": result.decision.value,
            "reason": result.reason,
            "server_available": result.server_available,
            "privacy": {
                "level": result.privacy.level.value if result.privacy else None,
                "categories": [c.value for c in result.privacy.categories] if result.privacy else [],
                "should_stay_local": result.privacy.should_stay_local if result.privacy else False,
            } if result.privacy else None,
            "suggested_instrument": result.suggested_instrument,
        }

    @app.post("/privacy/check")
    async def check_privacy(request: PrivacyCheckRequest):
        """Check if a query is privacy-sensitive.

        Returns privacy classification.
        """
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        assessment = _room.privacy_classifier.classify(request.query, request.context)

        return {
            "level": assessment.level.value,
            "categories": [c.value for c in assessment.categories],
            "confidence": assessment.confidence,
            "should_stay_local": assessment.should_stay_local,
            "reason": assessment.reason,
        }

    @app.get("/router/status")
    async def router_status():
        """Get router status including server availability."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        return _room.router.get_status()

    @app.post("/task/smart")
    async def smart_task(request: TaskRequest):
        """Execute a task with smart routing.

        Automatically decides local vs server based on:
        - Privacy sensitivity
        - Server availability
        - Required capabilities
        """
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        # Get routing decision
        routing = await _room.router.route(
            query=request.query,
            context=request.context,
            force_local=request.force_local,
        )

        # If local or server unavailable, execute locally
        if routing.decision == RoutingDecision.LOCAL or not routing.server_available:
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

        # Otherwise, indicate should go to server
        return {
            "routed_to": "server",
            "reason": routing.reason,
            "server_url": _room.router._server_url,
            "privacy": {
                "level": routing.privacy.level.value if routing.privacy else None,
                "should_stay_local": routing.privacy.should_stay_local if routing.privacy else False,
            },
        }

    # =========================================================================
    # Knowledge Sync (Phase 5B)
    # =========================================================================

    @app.get("/knowledge/cache")
    async def knowledge_cache_stats():
        """Get knowledge cache statistics."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        return _room.knowledge_cache.stats()

    @app.get("/knowledge/cache/entries")
    async def knowledge_cache_entries(category: str | None = None):
        """List cached knowledge entries.

        Args:
            category: Optional category filter
        """
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        entries = _room.knowledge_cache.get_entries(category=category)
        return {"entries": [e.model_dump() for e in entries]}

    @app.post("/knowledge/learnings/record")
    async def record_learning(request: RecordLearningRequest):
        """Manually record a learning observation."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        learning = LocalLearning(
            category=request.category,
            title=request.title,
            content=request.content,
            confidence=request.confidence,
            tags=request.tags,
        )
        _room.learning_reporter.record(learning)
        return {
            "recorded": True,
            "pending": _room.learning_reporter.pending_count,
        }

    @app.post("/knowledge/learnings/flush")
    async def flush_learnings():
        """Force flush buffered learnings to the server."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        count = await _room.learning_reporter.flush()
        return {
            "flushed": count,
            "pending": _room.learning_reporter.pending_count,
        }

    @app.get("/knowledge/learnings/stats")
    async def learning_stats():
        """Get learning reporter statistics."""
        if not _room:
            raise HTTPException(status_code=503, detail="Room not initialized")

        return _room.learning_reporter.stats()

    return app
