"""FastAPI routes for task submission and retrieval."""

import asyncio
import json
import logging
import time
from typing import Annotated, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from starlette.responses import StreamingResponse

from loop_symphony import __version__
from loop_symphony.api.auth import Auth, OptionalAuth, get_db_client
from loop_symphony.api.events import (
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_ITERATION,
    EVENT_STARTED,
    EventBus,
)
from loop_symphony.db.client import DatabaseClient
from conductors.reference.general_conductor import GeneralConductor
from loop_symphony.manager.heartbeat_worker import HeartbeatWorker
from loop_symphony.models.heartbeat import Heartbeat, HeartbeatCreate, HeartbeatUpdate
from loop_symphony.models.outcome import TaskStatus
from loop_symphony.models.process import ProcessType
from loop_symphony.models.finding import ExecutionMetadata, Finding
from loop_symphony.models.task import (
    TaskContext,
    TaskPendingResponse,
    TaskPlan,
    TaskPreferences,
    TaskRequest,
    TaskResponse,
    TaskSubmitResponse,
)
from loop_symphony.models.health import SystemHealth
from loop_symphony.manager.task_manager import TaskManager, TaskState
from loop_symphony.manager.error_tracker import ErrorTracker
from loop_symphony.manager.intervention_engine import InterventionEngine
from loop_symphony.manager.trust_tracker import TrustTracker
from loop_symphony.models.investigation_brief import (
    InvestigationBrief,
    LibrarianExecuteRequest,
    LibrarianPlan,
)
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.tools.registry import ToolRegistry
from loop_symphony.tools.tavily import TavilyClient
from librarian.catalog.planner import ArrangementPlanner, INSTRUMENT_CATALOG

logger = logging.getLogger(__name__)

router = APIRouter()

# Dependency injection
_conductor: GeneralConductor | None = None
_registry: ToolRegistry | None = None
_db_client: DatabaseClient | None = None
_event_bus: EventBus | None = None
_heartbeat_worker: HeartbeatWorker | None = None
_trust_tracker: TrustTracker | None = None
_task_manager: TaskManager | None = None
_error_tracker: ErrorTracker | None = None
_intervention_engine: InterventionEngine | None = None


def _build_registry() -> ToolRegistry:
    """Create and populate the tool registry."""
    registry = ToolRegistry()
    registry.register(ClaudeClient())
    registry.register(TavilyClient())
    return registry


def get_conductor() -> GeneralConductor:
    """Get or create conductor instance."""
    global _conductor, _registry
    if _conductor is None:
        _registry = _build_registry()
        _conductor = GeneralConductor(registry=_registry)
    return _conductor


_arrangement_planner: ArrangementPlanner | None = None


def get_arrangement_planner() -> ArrangementPlanner:
    """Get or create arrangement planner instance."""
    global _arrangement_planner, _registry
    if _arrangement_planner is None:
        if _registry is None:
            _registry = _build_registry()
        claude = _registry.get_by_capability("reasoning")
        _arrangement_planner = ArrangementPlanner(claude=claude, registry=_registry)
    return _arrangement_planner


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


def get_heartbeat_worker() -> HeartbeatWorker:
    """Get or create heartbeat worker instance."""
    global _heartbeat_worker
    if _heartbeat_worker is None:
        _heartbeat_worker = HeartbeatWorker(
            db=get_db_client(),
            conductor=get_conductor(),
        )
    return _heartbeat_worker


def get_trust_tracker() -> TrustTracker:
    """Get or create trust tracker instance."""
    global _trust_tracker
    if _trust_tracker is None:
        _trust_tracker = TrustTracker()
    return _trust_tracker


def get_task_manager() -> TaskManager:
    """Get or create task manager instance."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager


def get_error_tracker() -> ErrorTracker:
    """Get or create error tracker instance."""
    global _error_tracker
    if _error_tracker is None:
        _error_tracker = ErrorTracker()
    return _error_tracker


def get_intervention_engine() -> InterventionEngine:
    """Get or create intervention engine instance."""
    global _intervention_engine
    if _intervention_engine is None:
        _intervention_engine = InterventionEngine(
            error_tracker=get_error_tracker(),
            trust_tracker=get_trust_tracker(),
        )
    return _intervention_engine



async def execute_task_background(
    request: TaskRequest,
    conductor: GeneralConductor,
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
    task_manager = get_task_manager()
    task_id = request.id

    try:
        # Update status to running
        await db.update_task_status(request.id, TaskStatus.RUNNING)
        event_bus.emit(request.id, {"event": EVENT_STARTED})

        # Create checkpoint callback bound to this task
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
            # Update task manager with progress
            await task_manager.update_progress(
                task_id, iteration_num, f"Phase: {phase}"
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
        response = await conductor.handle(request)

        # Post-task interventions (fail-open)
        try:
            engine = get_intervention_engine()
            intervention_result = engine.evaluate_task(request, response)
            if intervention_result.interventions:
                response = InterventionEngine.enrich_response(
                    response, intervention_result
                )
        except Exception as intervention_err:
            logger.warning(f"Intervention evaluation failed: {intervention_err}")

        # Update database with result
        await db.complete_task(request.id, response)

        # Mark as complete in task manager
        await task_manager.complete_task(task_id)

        # Track trust metrics if we have app context
        context = request.context
        if context and context.app_id:
            try:
                trust_tracker = get_trust_tracker()
                trust_tracker.record_outcome(
                    app_id=UUID(context.app_id),
                    outcome=response.outcome,
                    user_id=UUID(context.user_id) if context.user_id else None,
                )
            except Exception as trust_err:
                logger.warning(f"Failed to track trust metrics: {trust_err}")

        event_bus.emit(request.id, {
            "event": EVENT_COMPLETE,
            "outcome": response.outcome.value,
            "summary": response.summary,
            "confidence": response.confidence,
        })

    except asyncio.CancelledError:
        # Task was cancelled by user
        logger.info(f"Task {task_id} was cancelled")
        await task_manager.mark_cancelled(task_id)
        await db.update_task_status(task_id, TaskStatus.FAILED, error="Cancelled by user")
        event_bus.emit(task_id, {"event": EVENT_ERROR, "error": "Task cancelled"})

    except Exception as e:
        logger.error(f"Task {request.id} failed: {e}")
        await task_manager.fail_task(task_id, str(e))
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


@router.get("/health/system", response_model=SystemHealth)
async def system_health() -> SystemHealth:
    """Get detailed system health status.

    Returns comprehensive health information from the autonomic layer:
    - Overall status (healthy, degraded, critical)
    - Component health (database, tools)
    - Uptime and statistics
    - Error tracking

    This endpoint is used by external monitoring systems.
    """
    from loop_symphony.main import get_system_health
    return get_system_health()


@router.get("/health/database")
async def database_health(
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> dict:
    """Check database connectivity.

    Performs a simple query to verify the database is reachable.

    Returns:
        Dict with healthy status, latency, and any error
    """
    return await db.health_check()


# Instrument descriptions for plans
_INSTRUMENT_DESCRIPTIONS = {
    "note": "Quick, single-pass reasoning for simple questions",
    "research": "Multi-iteration research with web search and analysis",
    "synthesis": "Combines multiple inputs into coherent output",
    "vision": "Analyzes images and extracts information",
}

_INSTRUMENT_ITERATIONS = {
    "note": 1,
    "research": 5,
    "synthesis": 2,
    "vision": 3,
}


@router.post("/task", response_model=TaskSubmitResponse)
async def submit_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    conductor: Annotated[GeneralConductor, Depends(get_conductor)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    auth: OptionalAuth = None,
) -> TaskSubmitResponse:
    """Submit a new task for processing.

    The task is stored in the database and executed asynchronously.
    Returns immediately with a task_id for polling.

    Trust levels:
    - Level 0 (supervised): Returns a plan for approval before executing
    - Level 1 (semi): Executes immediately, returns results
    - Level 2 (auto): Executes immediately, minimal output

    Optionally accepts X-Api-Key and X-User-Id headers for authentication.
    When provided, the app_id and user_id are injected into the task context.

    Args:
        request: The task request
        background_tasks: FastAPI background tasks
        conductor: The conductor instance
        db: The database client
        event_bus: The event bus for SSE streaming
        auth: Optional authentication context

    Returns:
        TaskSubmitResponse with task_id (and plan if trust_level=0)
    """
    # Inject auth context if provided
    if auth:
        context = request.context or TaskContext()
        context = context.model_copy(update={
            "app_id": str(auth.app.id),
            "user_id": str(auth.user.id) if auth.user else None,
        })
        request = request.model_copy(update={"context": context})
        logger.info(
            f"Received task: {request.id} - {request.query[:50]}... "
            f"(app={auth.app.name})"
        )
    else:
        logger.info(f"Received task: {request.id} - {request.query[:50]}...")

    # Get trust level (default to 0 = supervised)
    trust_level = 0
    if request.preferences:
        trust_level = request.preferences.trust_level

    # Analyze which instrument would be used
    instrument_name = await conductor.route(request)
    process_type = ProcessType.SEMI_AUTONOMIC
    from conductors.reference.general_conductor import _INSTRUMENT_PROCESS_TYPE
    if instrument_name in _INSTRUMENT_PROCESS_TYPE:
        process_type = _INSTRUMENT_PROCESS_TYPE[instrument_name]

    # Trust level 0: Return plan for approval, don't execute yet
    if trust_level == 0:
        await db.create_task(request)
        await db.update_task_status(request.id, TaskStatus.AWAITING_APPROVAL)

        plan = TaskPlan(
            task_id=request.id,
            query=request.query,
            instrument=instrument_name,
            process_type=process_type.value,
            estimated_iterations=_INSTRUMENT_ITERATIONS.get(instrument_name, 1),
            description=_INSTRUMENT_DESCRIPTIONS.get(
                instrument_name,
                f"Process query using {instrument_name} instrument"
            ),
            requires_approval=True,
        )

        logger.info(
            f"Task {request.id} awaiting approval (trust_level=0, "
            f"instrument={instrument_name})"
        )

        return TaskSubmitResponse(
            task_id=request.id,
            status=TaskStatus.AWAITING_APPROVAL,
            message="Task plan ready for approval. Call POST /task/{id}/approve to execute.",
            plan=plan,
        )

    # Trust level 1 or 2: Execute immediately
    await db.create_task(request)

    # Register with task manager for tracking
    task_manager = get_task_manager()
    context = request.context
    await task_manager.register_task(
        task_id=request.id,
        query=request.query,
        instrument=instrument_name,
        app_id=context.app_id if context else None,
        user_id=context.user_id if context else None,
    )

    # Create asyncio task for cancellation support
    asyncio_task = asyncio.create_task(
        execute_task_background(request, conductor, db, event_bus)
    )
    await task_manager.start_task(
        request.id,
        asyncio_task,
        max_iterations=_INSTRUMENT_ITERATIONS.get(instrument_name, 5),
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


# -----------------------------------------------------------------------------
# Heartbeat endpoints (require authentication)
# -----------------------------------------------------------------------------


@router.post("/heartbeats", response_model=Heartbeat, status_code=status.HTTP_201_CREATED)
async def create_heartbeat(
    data: HeartbeatCreate,
    auth: Auth,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> Heartbeat:
    """Create a new heartbeat for scheduled task execution.

    Heartbeats define recurring tasks that will be executed on a schedule.
    The query_template can contain placeholders like {date} that are expanded
    at execution time.

    Args:
        data: The heartbeat creation data
        auth: Authentication context (required)
        db: The database client

    Returns:
        The created heartbeat
    """
    user_id = auth.user.id if auth.user else None
    heartbeat = await db.create_heartbeat(auth.app.id, user_id, data)
    logger.info(
        f"Created heartbeat {heartbeat.id} for app={auth.app.name} "
        f"cron={data.cron_expression}"
    )
    return heartbeat


@router.get("/heartbeats", response_model=list[Heartbeat])
async def list_heartbeats(
    auth: Auth,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> list[Heartbeat]:
    """List all heartbeats for the authenticated app/user.

    Args:
        auth: Authentication context (required)
        db: The database client

    Returns:
        List of heartbeats
    """
    user_id = auth.user.id if auth.user else None
    return await db.list_heartbeats(auth.app.id, user_id)


# -----------------------------------------------------------------------------
# Heartbeat tick/status endpoints (must be before parameterized routes)
# -----------------------------------------------------------------------------


@router.post("/heartbeats/tick")
async def heartbeat_tick(
    worker: Annotated[HeartbeatWorker, Depends(get_heartbeat_worker)],
) -> dict:
    """Process all due heartbeats.

    This endpoint checks all active heartbeats, determines which are due
    based on their cron expressions, and executes them.

    Can be called:
    - Manually via curl for testing
    - By an external scheduler (cron, Railway cron, etc.)
    - By the autonomic layer's background scheduler

    Returns:
        Summary of processed and skipped heartbeats
    """
    return await worker.tick()


@router.get("/heartbeats/status")
async def heartbeat_status(
    worker: Annotated[HeartbeatWorker, Depends(get_heartbeat_worker)],
) -> dict:
    """Get status of all active heartbeats.

    Returns information about each heartbeat including when it last ran
    and when it's next due.

    Returns:
        List of heartbeat statuses
    """
    from croniter import croniter
    from datetime import datetime, UTC

    result = (
        worker.db.client.table("heartbeats")
        .select("*")
        .eq("is_active", True)
        .execute()
    )

    heartbeats = [Heartbeat(**row) for row in result.data]
    statuses = []

    for hb in heartbeats:
        last_run = await worker.get_last_run_at(hb.id)
        now = datetime.now(UTC)

        try:
            cron = croniter(hb.cron_expression, now)
            next_run = cron.get_next(datetime)
        except Exception:
            next_run = None

        statuses.append({
            "id": str(hb.id),
            "name": hb.name,
            "cron_expression": hb.cron_expression,
            "is_active": hb.is_active,
            "last_run_at": last_run.isoformat() if last_run else None,
            "next_scheduled": next_run.isoformat() if next_run else None,
            "is_due": worker._is_heartbeat_due(hb, last_run),
        })

    return {"heartbeats": statuses}


# -----------------------------------------------------------------------------
# Heartbeat CRUD with ID parameter
# -----------------------------------------------------------------------------


@router.get("/heartbeats/{heartbeat_id}", response_model=Heartbeat)
async def get_heartbeat(
    heartbeat_id: UUID,
    auth: Auth,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> Heartbeat:
    """Get a specific heartbeat by ID.

    Args:
        heartbeat_id: The heartbeat ID
        auth: Authentication context (required)
        db: The database client

    Returns:
        The heartbeat

    Raises:
        HTTPException: If heartbeat not found
    """
    heartbeat = await db.get_heartbeat(heartbeat_id, auth.app.id)
    if not heartbeat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Heartbeat not found",
        )
    return heartbeat


@router.patch("/heartbeats/{heartbeat_id}", response_model=Heartbeat)
async def update_heartbeat(
    heartbeat_id: UUID,
    updates: HeartbeatUpdate,
    auth: Auth,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> Heartbeat:
    """Update a heartbeat.

    Args:
        heartbeat_id: The heartbeat ID
        updates: The fields to update
        auth: Authentication context (required)
        db: The database client

    Returns:
        The updated heartbeat

    Raises:
        HTTPException: If heartbeat not found
    """
    heartbeat = await db.update_heartbeat(heartbeat_id, auth.app.id, updates)
    if not heartbeat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Heartbeat not found",
        )
    logger.info(f"Updated heartbeat {heartbeat_id}")
    return heartbeat


@router.delete("/heartbeats/{heartbeat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_heartbeat(
    heartbeat_id: UUID,
    auth: Auth,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> None:
    """Delete a heartbeat.

    Args:
        heartbeat_id: The heartbeat ID
        auth: Authentication context (required)
        db: The database client

    Raises:
        HTTPException: If heartbeat not found
    """
    deleted = await db.delete_heartbeat(heartbeat_id, auth.app.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Heartbeat not found",
        )
    logger.info(f"Deleted heartbeat {heartbeat_id}")


# -------------------------------------------------------------------------
# Task Management Endpoints
# -------------------------------------------------------------------------


@router.get("/tasks/active")
async def get_active_tasks(
    auth: OptionalAuth = None,
    task_manager: Annotated[TaskManager, Depends(get_task_manager)] = None,
) -> list[dict]:
    """Get all currently active (running or queued) tasks.

    This implements "What are you working on?" for the semi-autonomic layer.

    Args:
        auth: Optional authentication context (filters by app if provided)
        task_manager: The task manager instance

    Returns:
        List of active task information
    """
    if task_manager is None:
        task_manager = get_task_manager()

    app_id = str(auth.app.id) if auth else None
    user_id = str(auth.user.id) if auth and auth.user else None

    active = task_manager.get_active_tasks(app_id=app_id, user_id=user_id)
    return [t.to_dict() for t in active]


@router.get("/tasks/recent")
async def get_recent_tasks(
    limit: int = 20,
    auth: OptionalAuth = None,
    task_manager: Annotated[TaskManager, Depends(get_task_manager)] = None,
) -> list[dict]:
    """Get recent tasks (for monitoring/debugging).

    Args:
        limit: Maximum number of tasks to return (default 20)
        auth: Optional authentication context
        task_manager: The task manager instance

    Returns:
        List of recent task information
    """
    if task_manager is None:
        task_manager = get_task_manager()

    app_id = str(auth.app.id) if auth else None
    tasks = task_manager.get_all_tasks(limit=limit, app_id=app_id)
    return [t.to_dict() for t in tasks]


@router.post("/task/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    task_manager: Annotated[TaskManager, Depends(get_task_manager)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> dict:
    """Cancel a running task.

    Requests cancellation of the task. The task will be marked as cancelled
    and its asyncio.Task will be cancelled. The actual cancellation may take
    a moment as the task needs to reach a cancellation point.

    Args:
        task_id: The task ID to cancel
        task_manager: The task manager instance
        db: The database client

    Returns:
        Status of the cancellation request

    Raises:
        HTTPException: If task not found or not running
    """
    managed = task_manager.get_task(task_id)

    if not managed:
        # Check if it exists in the database but not in memory
        task_data = await db.get_task(task_id)
        if not task_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )
        # Task exists but isn't running
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is not currently running (status: {task_data['status']})",
        )

    if managed.state != TaskState.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is not running (state: {managed.state.value})",
        )

    cancelled = await task_manager.cancel_task(task_id)

    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not cancel task {task_id}",
        )

    return {
        "task_id": task_id,
        "status": "cancelling",
        "message": "Cancellation requested. Task will be cancelled shortly.",
    }






# ── Librarian Endpoints ────────────────────────────────────────────────


@router.get("/librarian/catalog")
async def librarian_catalog() -> dict:
    """Return the full instrument catalog with metadata.

    Includes executable status and conductor assignment for each instrument.
    """
    return INSTRUMENT_CATALOG


@router.post("/librarian/plan")
async def librarian_plan(
    brief: InvestigationBrief,
    planner: Annotated[ArrangementPlanner, Depends(get_arrangement_planner)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> LibrarianPlan:
    """Plan an investigation from a structured brief.

    Saves the brief to the database, runs the Librarian planner,
    and returns a LibrarianPlan with the proposed arrangement.
    """
    # Save the brief to Supabase
    brief_row = await db.create_investigation_brief({
        "deliverable": brief.deliverable,
        "context": brief.context,
        "proposed_approach": brief.proposed_approach,
        "tools_and_data": brief.tools_and_data,
        "exclusions": brief.exclusions,
        "precision": brief.precision,
        "intent": brief.intent,
        "conductor_context": brief.conductor_context,
        "plan_status": "planning",
    })
    brief_id = brief_row.get("id")

    try:
        plan = await planner.plan_from_brief(brief)

        # Update brief with the generated plan
        if brief_id:
            await db.update_investigation_brief(brief_id, {
                "librarian_plan": plan.model_dump(mode="json"),
                "plan_status": "planned",
            })

        return plan
    except Exception as e:
        logger.error(f"Librarian planning failed: {e}")
        if brief_id:
            await db.update_investigation_brief(brief_id, {
                "plan_status": "failed",
            })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Planning failed: {e}",
        )


@router.post("/librarian/execute")
async def librarian_execute(
    request: LibrarianExecuteRequest,
    conductor: Annotated[GeneralConductor, Depends(get_conductor)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    background_tasks: BackgroundTasks,
) -> TaskSubmitResponse:
    """Execute an approved Librarian plan.

    Creates an intelligence artifact, builds a TaskRequest from the brief,
    and runs the task in the background.
    """
    brief_id = request.brief_id
    plan = request.plan

    # Fetch the original brief from the database
    brief_row = await db.get_investigation_brief(brief_id)
    if brief_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation brief {brief_id} not found",
        )

    deliverable = brief_row.get("deliverable", "")
    intent = brief_row.get("intent")

    # Determine conductor name from the plan
    conductor_name = (
        plan.conductors_involved[0] if plan.conductors_involved else "librarian"
    )

    # Determine loop names from the proposal steps/branches
    loop_names: list[str] = []
    if plan.proposal.steps:
        loop_names = [s.instrument for s in plan.proposal.steps]
    elif plan.proposal.branches:
        loop_names = plan.proposal.branches
    elif plan.proposal.instrument:
        loop_names = [plan.proposal.instrument]

    # Create intelligence artifact with status "running"
    artifact_row = await db.create_intelligence_artifact({
        "conductor_name": conductor_name,
        "card_type": "investigation",
        "headline": deliverable,
        "reasoning_preview": plan.proposal.rationale,
        "full_reasoning": {},
        "symphony_name": f"{plan.proposal.type}_arrangement",
        "loop_names": loop_names,
        "trust_level": 1,
        "confidence": None,
        "data_sources": [],
        "is_pinned": False,
        "status": "running",
        "brief_id": brief_id,
    })
    artifact_id = artifact_row.get("id")

    # Link artifact back to the brief
    await db.update_investigation_brief(brief_id, {
        "artifact_id": artifact_id,
        "plan_status": "running",
    })

    # Build a TaskRequest from the brief — pass ALL 7 fields so instruments can use them
    brief_data = {
        "deliverable": deliverable,
        "context": brief_row.get("context"),
        "proposed_approach": brief_row.get("proposed_approach"),
        "tools_and_data": brief_row.get("tools_and_data"),
        "exclusions": brief_row.get("exclusions"),
        "precision": brief_row.get("precision"),
        "intent": brief_row.get("intent"),
        "conductor_context": brief_row.get("conductor_context"),
    }

    # Map precision field to thoroughness preference
    precision = brief_row.get("precision", "") or ""
    precision_lower = precision.lower()
    if any(w in precision_lower for w in ("ballpark", "quick", "rough", "fast")):
        thoroughness = "quick"
    elif any(w in precision_lower for w in ("precise", "exact", "thorough", "detailed", "rigorous")):
        thoroughness = "thorough"
    else:
        thoroughness = "balanced"

    task_request = TaskRequest(
        query=deliverable,
        context=TaskContext(
            conversation_summary=brief_row.get("context"),
            goal=brief_row.get("intent"),
            investigation_brief=brief_data,
        ),
        preferences=TaskPreferences(
            thoroughness=thoroughness,
            trust_level=1,
        ),
    )

    # Register task with task manager
    task_manager = get_task_manager()
    await task_manager.register_task(
        task_id=str(task_request.id),
        query=task_request.query,
        instrument=conductor_name,
    )

    # Create task in database
    await db.create_task(task_request)

    # Determine which instrument the Librarian plan chose
    if plan.proposal.instrument:
        instrument_name = plan.proposal.instrument
    elif plan.proposal.steps:
        instrument_name = plan.proposal.steps[0].instrument
    else:
        instrument_name = "research"

    # Execute in background — directly with the planned instrument, no GeneralConductor
    background_tasks.add_task(
        _execute_librarian_task,
        task_request=task_request,
        conductor=conductor,
        instrument_name=instrument_name,
        plan=plan,
        db=db,
        event_bus=event_bus,
        artifact_id=artifact_id,
        brief_id=brief_id,
        intent=intent,
    )

    return TaskSubmitResponse(
        task_id=task_request.id,
        status=TaskStatus.RUNNING.value,
        message=f"Librarian investigation started (instrument: {instrument_name})",
    )


async def _execute_librarian_task(
    task_request: TaskRequest,
    conductor: GeneralConductor,
    instrument_name: str,
    plan: LibrarianPlan,
    db: DatabaseClient,
    event_bus: EventBus,
    artifact_id: str,
    brief_id: str,
    intent: str | None,
) -> None:
    """Background execution for a librarian-initiated task.

    Runs the instrument chosen by the Librarian plan directly — bypasses
    the GeneralConductor's keyword routing so the plan is respected.
    """
    task_id = task_request.id
    task_manager = get_task_manager()

    try:
        await db.update_task_status(task_id, TaskStatus.RUNNING)
        event_bus.emit(task_id, {"event": EVENT_STARTED})

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
            await task_manager.update_progress(
                task_id, iteration_num, f"Phase: {phase}"
            )
            event_bus.emit(task_id, {
                "event": EVENT_ITERATION,
                "iteration_num": iteration_num,
                "phase": phase,
                "data": output_data,
                "duration_ms": duration_ms,
            })

        context = task_request.context or TaskContext()
        context = context.model_copy(update={"checkpoint_fn": _checkpoint})

        # Execute the planned instrument directly
        instrument = conductor.instruments.get(instrument_name)
        if instrument is None:
            raise ValueError(f"Unknown instrument: {instrument_name}")

        start_time = time.time()
        result = await instrument.execute(task_request.query, context)
        duration_ms = int((time.time() - start_time) * 1000)

        # Convert loop_library Finding instances to server Finding instances
        # (identical schema, different module paths — Pydantic rejects cross-package models)
        server_findings = [
            Finding.model_validate(f.model_dump()) for f in (result.findings or [])
        ]

        response = TaskResponse(
            request_id=task_id,
            outcome=result.outcome,
            findings=server_findings,
            summary=result.summary,
            confidence=result.confidence,
            metadata=ExecutionMetadata(
                instrument_used=instrument_name,
                iterations=result.iterations,
                duration_ms=duration_ms,
                sources_consulted=result.sources_consulted,
            ),
            discrepancy=result.discrepancy,
            suggested_followups=result.suggested_followups,
        )

        # Complete the task in the database
        await db.complete_task(task_id, response)
        event_bus.emit(task_id, {
            "event": EVENT_COMPLETE,
            "outcome": response.outcome.value if response.outcome else "complete",
        })

        # Build the reasoning preview from the most interesting finding
        reasoning_preview = ""
        if response.findings:
            reasoning_preview = response.findings[0].content[:500]
        elif response.summary:
            reasoning_preview = response.summary[:500]

        # Frame conclusion around intent if provided
        conclusion = response.summary or ""
        if intent and conclusion:
            conclusion = f"Regarding '{intent}': {conclusion}"

        # Build full reasoning JSON — includes everything Kiloa needs to display
        full_reasoning = {
            "summary": response.summary,
            "findings": [
                {
                    "content": f.content,
                    "confidence": f.confidence,
                    "source": f.source,
                }
                for f in (response.findings or [])
            ],
            "metadata": response.metadata.model_dump(mode="json") if response.metadata else {},
            "plan": {
                "instrument": instrument_name,
                "type": plan.proposal.type,
                "rationale": plan.proposal.rationale,
                "estimated_iterations": plan.estimated_duration_seconds,
            },
            "original_query": task_request.query,
            "execution": {
                "instrument_used": instrument_name,
                "iterations": result.iterations,
                "outcome": result.outcome.value,
                "duration_ms": duration_ms,
                "sources_consulted": result.sources_consulted,
                "suggested_followups": result.suggested_followups,
            },
        }

        # Update intelligence artifact to complete
        await db.update_intelligence_artifact(artifact_id, {
            "status": "complete",
            "reasoning_preview": reasoning_preview,
            "full_reasoning": full_reasoning,
            "conclusion": conclusion,
            "confidence": response.confidence,
            "data_sources": (
                response.metadata.sources_consulted if response.metadata else []
            ),
        })

        # Update brief status
        await db.update_investigation_brief(brief_id, {
            "plan_status": "complete",
        })

    except Exception as e:
        logger.error(f"Librarian task {task_id} failed: {e}")
        await db.update_task_status(task_id, TaskStatus.FAILED, error=str(e))
        event_bus.emit(task_id, {"event": EVENT_ERROR, "error": str(e)})

        # Mark artifact as failed
        try:
            await db.update_intelligence_artifact(artifact_id, {
                "status": "failed",
                "full_reasoning": {"error": str(e)},
            })
            await db.update_investigation_brief(brief_id, {
                "plan_status": "failed",
            })
        except Exception:
            logger.error(f"Failed to update artifact/brief status for task {task_id}")

    finally:
        task_manager.deregister(task_id)
