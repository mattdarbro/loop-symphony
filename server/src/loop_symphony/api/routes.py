"""FastAPI routes for task submission and retrieval."""

import asyncio
import json
import logging
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from starlette.responses import StreamingResponse

from loop_symphony import __version__
from loop_symphony.api.events import (
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_ITERATION,
    EVENT_STARTED,
    EventBus,
)
from loop_symphony.db.client import DatabaseClient
from loop_symphony.manager.conductor import Conductor
from loop_symphony.models.outcome import TaskStatus
from loop_symphony.models.task import (
    TaskContext,
    TaskPendingResponse,
    TaskRequest,
    TaskResponse,
    TaskSubmitResponse,
)
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.tools.registry import ToolRegistry
from loop_symphony.tools.tavily import TavilyClient

logger = logging.getLogger(__name__)

router = APIRouter()

# Dependency injection
_conductor: Conductor | None = None
_registry: ToolRegistry | None = None
_db_client: DatabaseClient | None = None
_event_bus: EventBus | None = None


def _build_registry() -> ToolRegistry:
    """Create and populate the tool registry."""
    registry = ToolRegistry()
    registry.register(ClaudeClient())
    registry.register(TavilyClient())
    return registry


def get_conductor() -> Conductor:
    """Get or create conductor instance."""
    global _conductor, _registry
    if _conductor is None:
        _registry = _build_registry()
        _conductor = Conductor(registry=_registry)
    return _conductor


def get_db_client() -> DatabaseClient:
    """Get or create database client instance."""
    global _db_client
    if _db_client is None:
        _db_client = DatabaseClient()
    return _db_client


def get_event_bus() -> EventBus:
    """Get or create event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


async def execute_task_background(
    request: TaskRequest,
    conductor: Conductor,
    db: DatabaseClient,
    event_bus: EventBus,
) -> None:
    """Execute task in background and update database.

    Args:
        request: The task request
        conductor: The conductor instance
        db: The database client
        event_bus: The event bus for SSE streaming
    """
    try:
        # Update status to running
        await db.update_task_status(request.id, TaskStatus.RUNNING)
        event_bus.emit(request.id, {"event": EVENT_STARTED})

        # Create checkpoint callback bound to this task
        task_id = request.id

        async def _checkpoint(
            iteration_num: int,
            phase: str,
            input_data: dict,
            output_data: dict,
            duration_ms: int,
        ) -> None:
            await db.record_iteration(
                task_id, iteration_num, phase, input_data, output_data, duration_ms
            )
            event_bus.emit(task_id, {
                "event": EVENT_ITERATION,
                "iteration_num": iteration_num,
                "phase": phase,
                "data": output_data,
                "duration_ms": duration_ms,
            })

        # Inject checkpoint callback into context
        context = request.context or TaskContext()
        request.context = context.model_copy(update={"checkpoint_fn": _checkpoint})

        # Execute the task
        response = await conductor.execute(request)

        # Update database with result
        await db.complete_task(request.id, response)

        event_bus.emit(request.id, {
            "event": EVENT_COMPLETE,
            "outcome": response.outcome.value,
            "summary": response.summary,
            "confidence": response.confidence,
        })

    except Exception as e:
        logger.error(f"Task {request.id} failed: {e}")
        await db.fail_task(request.id, str(e))
        event_bus.emit(request.id, {"event": EVENT_ERROR, "error": str(e)})


@router.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    response: dict = {
        "status": "ok",
        "version": __version__,
    }
    if _registry is not None:
        response["tools"] = sorted(tool.name for tool in _registry.get_all())
    return response


@router.post("/task", response_model=TaskSubmitResponse)
async def submit_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    conductor: Annotated[Conductor, Depends(get_conductor)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> TaskSubmitResponse:
    """Submit a new task for processing.

    The task is stored in the database and executed asynchronously.
    Returns immediately with a task_id for polling.

    Args:
        request: The task request
        background_tasks: FastAPI background tasks
        conductor: The conductor instance
        db: The database client
        event_bus: The event bus for SSE streaming

    Returns:
        TaskSubmitResponse with task_id
    """
    logger.info(f"Received task: {request.id} - {request.query[:50]}...")

    # Store task in database
    await db.create_task(request)

    # Schedule background execution
    background_tasks.add_task(
        execute_task_background,
        request,
        conductor,
        db,
        event_bus,
    )

    return TaskSubmitResponse(
        task_id=request.id,
        status=TaskStatus.PENDING,
        message="Task submitted successfully",
    )


@router.get("/task/{task_id}")
async def get_task(
    task_id: str,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> TaskResponse | TaskPendingResponse:
    """Get task status or result.

    Args:
        task_id: The task ID to retrieve
        db: The database client

    Returns:
        TaskResponse if complete, TaskPendingResponse if still running

    Raises:
        HTTPException: If task not found
    """
    task_data = await db.get_task(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    task_status = TaskStatus(task_data["status"])

    # If complete, return full response
    if task_status == TaskStatus.COMPLETE and task_data.get("response"):
        return TaskResponse(**task_data["response"])

    # If failed, raise error
    if task_status == TaskStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task failed: {task_data.get('error', 'Unknown error')}",
        )

    # Otherwise return pending status
    return TaskPendingResponse(
        task_id=task_id,
        status=task_status,
        progress=f"Task is {task_status.value}",
        started_at=task_data.get("created_at"),
    )


@router.get("/task/{task_id}/checkpoints")
async def get_task_checkpoints(
    task_id: str,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> list[dict]:
    """Get all checkpoints (iterations) for a task.

    Returns iteration records ordered by iteration_num and created_at.

    Args:
        task_id: The task ID
        db: The database client

    Returns:
        List of checkpoint records

    Raises:
        HTTPException: If task not found
    """
    task_data = await db.get_task(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    return await db.get_task_iterations(task_id)


@router.get("/task/{task_id}/stream")
async def stream_task(
    task_id: str,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> StreamingResponse:
    """Stream task events via Server-Sent Events.

    Late joiners receive the full event history before live events.
    The stream terminates after a complete or error event.

    Args:
        task_id: The task ID to stream
        db: The database client
        event_bus: The event bus

    Returns:
        StreamingResponse with text/event-stream content type

    Raises:
        HTTPException: If task not found
    """
    task_data = await db.get_task(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    queue = event_bus.subscribe(task_id)

    async def event_generator() -> AsyncIterator[str]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("event") in {EVENT_COMPLETE, EVENT_ERROR}:
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    # If task already has a terminal event, stop
                    if event_bus.has_terminal_event(task_id):
                        break
        finally:
            event_bus.unsubscribe(task_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
