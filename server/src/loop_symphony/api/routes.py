"""FastAPI routes for task submission and retrieval."""

import asyncio
import json
import logging
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
from loop_symphony.manager.conductor import Conductor
from loop_symphony.manager.heartbeat_worker import HeartbeatWorker
from loop_symphony.models.arrangement import ArrangementProposal, ArrangementValidation
from loop_symphony.models.heartbeat import Heartbeat, HeartbeatCreate, HeartbeatUpdate
from loop_symphony.models.loop_proposal import (
    LoopExecutionPlan,
    LoopProposal,
    LoopProposalValidation,
)
from loop_symphony.models.outcome import TaskStatus
from loop_symphony.models.saved_arrangement import (
    ArrangementSuggestion,
    SaveArrangementRequest,
    SavedArrangement,
)
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import (
    TaskContext,
    TaskPendingResponse,
    TaskPlan,
    TaskRequest,
    TaskResponse,
    TaskSubmitResponse,
)
from loop_symphony.models.trust import TrustLevelUpdate, TrustMetrics, TrustSuggestion
from loop_symphony.models.health import SystemHealth
from loop_symphony.manager.task_manager import TaskManager, TaskState
from loop_symphony.manager.trust_tracker import TrustTracker
from loop_symphony.manager.room_registry import RoomRegistry, RoomRegistration, RoomHeartbeat, RoomInfo
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
_heartbeat_worker: HeartbeatWorker | None = None
_trust_tracker: TrustTracker | None = None
_task_manager: TaskManager | None = None


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
        response = await conductor.execute(request)

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
    conductor: Annotated[Conductor, Depends(get_conductor)],
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
    instrument_name = await conductor.analyze_and_route(request)
    process_type = ProcessType.SEMI_AUTONOMIC
    from loop_symphony.manager.conductor import _INSTRUMENT_PROCESS_TYPE
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


@router.post("/task/{task_id}/approve", response_model=TaskSubmitResponse)
async def approve_task(
    task_id: str,
    conductor: Annotated[Conductor, Depends(get_conductor)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> TaskSubmitResponse:
    """Approve and execute a task that was submitted with trust_level=0.

    Args:
        task_id: The task ID to approve
        conductor: The conductor instance
        db: The database client
        event_bus: The event bus for SSE streaming

    Returns:
        TaskSubmitResponse indicating execution has started

    Raises:
        HTTPException: If task not found or not awaiting approval
    """
    task_data = await db.get_task(task_id)

    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    if task_data["status"] != TaskStatus.AWAITING_APPROVAL.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is not awaiting approval (status: {task_data['status']})",
        )

    # Reconstruct the request from stored data
    request = TaskRequest(**task_data["request"])

    # Update status
    await db.update_task_status(task_id, TaskStatus.PENDING)

    # Determine instrument for tracking
    instrument_name = await conductor.analyze_and_route(request)

    # Register with task manager
    task_manager = get_task_manager()
    context = request.context
    await task_manager.register_task(
        task_id=task_id,
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
        task_id,
        asyncio_task,
        max_iterations=_INSTRUMENT_ITERATIONS.get(instrument_name, 5),
    )

    logger.info(f"Task {task_id} approved and executing")

    return TaskSubmitResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Task approved and executing",
    )


# -------------------------------------------------------------------------
# Novel Arrangement Endpoints (Phase 3A)
# -------------------------------------------------------------------------


@router.post("/task/plan", response_model=ArrangementProposal)
async def plan_arrangement(
    request: TaskRequest,
    conductor: Annotated[Conductor, Depends(get_conductor)],
) -> ArrangementProposal:
    """Plan a novel arrangement for a task without executing.

    Uses Claude to analyze the query and propose the best instrument
    composition (single, sequential, or parallel).

    Args:
        request: The task request to plan for
        conductor: The conductor instance

    Returns:
        ArrangementProposal with recommended composition
    """
    logger.info(f"Planning arrangement for: {request.query[:50]}...")
    proposal = await conductor.plan_arrangement(request.query)
    return proposal


@router.post("/task/plan/validate", response_model=ArrangementValidation)
async def validate_arrangement(
    proposal: ArrangementProposal,
    conductor: Annotated[Conductor, Depends(get_conductor)],
) -> ArrangementValidation:
    """Validate an arrangement proposal.

    Checks that all instruments in the proposal exist and are available.

    Args:
        proposal: The arrangement proposal to validate
        conductor: The conductor instance

    Returns:
        ArrangementValidation with errors and warnings
    """
    validation = conductor.validate_arrangement(proposal)
    return validation


@router.post("/task/novel", response_model=TaskSubmitResponse)
async def submit_novel_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    conductor: Annotated[Conductor, Depends(get_conductor)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    auth: OptionalAuth = None,
) -> TaskSubmitResponse:
    """Submit a task using novel arrangement generation.

    Claude analyzes the query and proposes the best instrument composition,
    then executes it. This is "Level 4 creativity" from the PRD.

    Args:
        request: The task request
        background_tasks: FastAPI background tasks
        conductor: The conductor instance
        db: The database client
        event_bus: The event bus for SSE streaming
        auth: Optional authentication context

    Returns:
        TaskSubmitResponse with task_id
    """
    # Inject auth context if provided
    if auth:
        context = request.context or TaskContext()
        context = context.model_copy(update={
            "user_id": str(auth.user.id) if auth.user else None,
        })
        request = request.model_copy(update={"context": context})
        logger.info(
            f"Received novel task: {request.id} - {request.query[:50]}... "
            f"(app={auth.app.name})"
        )
    else:
        logger.info(f"Received novel task: {request.id} - {request.query[:50]}...")

    # Create task record
    await db.create_task(request)

    # Schedule novel arrangement execution
    async def execute_novel_background():
        try:
            await db.update_task_status(request.id, TaskStatus.RUNNING)
            event_bus.emit(request.id, EVENT_STARTED, {"task_id": request.id})

            response = await conductor.execute_novel(request)

            await db.update_task_response(request.id, response)
            await db.update_task_status(request.id, TaskStatus.COMPLETE)
            event_bus.emit(request.id, EVENT_COMPLETE, {
                "task_id": request.id,
                "outcome": response.outcome.value,
                "confidence": response.confidence,
            })

            logger.info(
                f"Novel task {request.id} complete: "
                f"outcome={response.outcome.value}, "
                f"instrument={response.metadata.instrument_used}"
            )
        except Exception as e:
            logger.error(f"Novel task {request.id} failed: {e}")
            await db.update_task_status(request.id, TaskStatus.FAILED)
            await db.update_task_error(request.id, str(e))
            event_bus.emit(request.id, EVENT_ERROR, {
                "task_id": request.id,
                "error": str(e),
            })

    background_tasks.add_task(execute_novel_background)

    return TaskSubmitResponse(
        task_id=request.id,
        status=TaskStatus.PENDING,
        message="Novel arrangement task submitted",
    )


# -------------------------------------------------------------------------
# Loop Proposal Endpoints (Phase 3B)
# -------------------------------------------------------------------------


@router.post("/task/loop/propose", response_model=LoopProposal)
async def propose_loop(
    request: TaskRequest,
    conductor: Annotated[Conductor, Depends(get_conductor)],
) -> LoopProposal:
    """Propose a new loop type for a task without executing.

    Level 5 creativity: Claude designs entirely new loop specifications
    with custom phases when existing instruments don't fit.

    Args:
        request: The task request to design a loop for
        conductor: The conductor instance

    Returns:
        LoopProposal with custom loop specification
    """
    logger.info(f"Proposing loop for: {request.query[:50]}...")
    proposal = await conductor.propose_loop(request.query)
    return proposal


@router.post("/task/loop/validate", response_model=LoopProposalValidation)
async def validate_loop_proposal(
    proposal: LoopProposal,
    conductor: Annotated[Conductor, Depends(get_conductor)],
) -> LoopProposalValidation:
    """Validate a loop proposal.

    Checks scientific method coverage, valid instruments,
    termination criteria, and iteration bounds.

    Args:
        proposal: The loop proposal to validate
        conductor: The conductor instance

    Returns:
        LoopProposalValidation with errors, warnings, and coverage
    """
    validation = conductor.validate_loop_proposal(proposal)
    return validation


@router.post("/task/loop/plan", response_model=LoopExecutionPlan)
async def get_loop_plan(
    proposal: LoopProposal,
    conductor: Annotated[Conductor, Depends(get_conductor)],
) -> LoopExecutionPlan:
    """Get an execution plan for a loop proposal.

    Returns validation results and execution estimates.
    Used for trust_level=0 approval workflow.

    Args:
        proposal: The loop proposal
        conductor: The conductor instance

    Returns:
        LoopExecutionPlan with estimates and validation
    """
    plan = conductor.get_loop_execution_plan(proposal)
    return plan


@router.post("/task/loop", response_model=TaskSubmitResponse)
async def submit_loop_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    conductor: Annotated[Conductor, Depends(get_conductor)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
    auth: OptionalAuth = None,
) -> TaskSubmitResponse:
    """Submit a task using loop proposal generation.

    Claude proposes and executes a custom loop specification.
    This is "Level 5 creativity" from the PRD - entirely new loop types.

    Args:
        request: The task request
        background_tasks: FastAPI background tasks
        conductor: The conductor instance
        db: The database client
        event_bus: The event bus for SSE streaming
        auth: Optional authentication context

    Returns:
        TaskSubmitResponse with task_id
    """
    # Inject auth context if provided
    if auth:
        context = request.context or TaskContext()
        context = context.model_copy(update={
            "user_id": str(auth.user.id) if auth.user else None,
        })
        request = request.model_copy(update={"context": context})
        logger.info(
            f"Received loop task: {request.id} - {request.query[:50]}... "
            f"(app={auth.app.name})"
        )
    else:
        logger.info(f"Received loop task: {request.id} - {request.query[:50]}...")

    # Create task record
    await db.create_task(request)

    # Schedule loop proposal execution
    async def execute_loop_background():
        try:
            await db.update_task_status(request.id, TaskStatus.RUNNING)
            event_bus.emit(request.id, EVENT_STARTED, {"task_id": request.id})

            response = await conductor.execute_proposed_loop(request)

            await db.update_task_response(request.id, response)
            await db.update_task_status(request.id, TaskStatus.COMPLETE)
            event_bus.emit(request.id, EVENT_COMPLETE, {
                "task_id": request.id,
                "outcome": response.outcome.value,
                "confidence": response.confidence,
            })

            logger.info(
                f"Loop task {request.id} complete: "
                f"outcome={response.outcome.value}, "
                f"loop={response.metadata.instrument_used}"
            )
        except Exception as e:
            logger.error(f"Loop task {request.id} failed: {e}")
            await db.update_task_status(request.id, TaskStatus.FAILED)
            await db.update_task_error(request.id, str(e))
            event_bus.emit(request.id, EVENT_ERROR, {
                "task_id": request.id,
                "error": str(e),
            })

    background_tasks.add_task(execute_loop_background)

    return TaskSubmitResponse(
        task_id=request.id,
        status=TaskStatus.PENDING,
        message="Loop proposal task submitted",
    )


# -------------------------------------------------------------------------
# Saved Arrangement Endpoints (Phase 3C: Meta-Learning)
# -------------------------------------------------------------------------


@router.get("/arrangements", response_model=list[SavedArrangement])
async def list_saved_arrangements(
    conductor: Annotated[Conductor, Depends(get_conductor)],
    auth: OptionalAuth = None,
) -> list[SavedArrangement]:
    """List all saved arrangements.

    Returns global arrangements and app-specific ones if authenticated.

    Args:
        conductor: The conductor instance
        auth: Optional authentication context

    Returns:
        List of saved arrangements
    """
    app_id = auth.app.id if auth else None
    return conductor.tracker.get_saved_arrangements(app_id)


@router.post("/arrangements", response_model=SavedArrangement)
async def save_arrangement(
    request: SaveArrangementRequest,
    conductor: Annotated[Conductor, Depends(get_conductor)],
    auth: OptionalAuth = None,
) -> SavedArrangement:
    """Save an arrangement for future reuse.

    Args:
        request: The save request with arrangement and metadata
        conductor: The conductor instance
        auth: Optional authentication context

    Returns:
        The saved arrangement

    Raises:
        HTTPException: If arrangement name already exists
    """
    app_id = auth.app.id if auth else None

    try:
        saved = conductor.tracker.save_arrangement(request, app_id)
        logger.info(f"Saved arrangement '{saved.name}' (id={saved.id})")
        return saved
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/arrangements/{arrangement_id}", response_model=SavedArrangement)
async def get_saved_arrangement(
    arrangement_id: str,
    conductor: Annotated[Conductor, Depends(get_conductor)],
) -> SavedArrangement:
    """Get a saved arrangement by ID.

    Args:
        arrangement_id: The arrangement ID
        conductor: The conductor instance

    Returns:
        The saved arrangement

    Raises:
        HTTPException: If not found
    """
    saved = conductor.tracker.get_saved_arrangement(arrangement_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement {arrangement_id} not found",
        )
    return saved


@router.delete("/arrangements/{arrangement_id}")
async def delete_saved_arrangement(
    arrangement_id: str,
    conductor: Annotated[Conductor, Depends(get_conductor)],
) -> dict[str, str]:
    """Delete a saved arrangement.

    Args:
        arrangement_id: The arrangement ID
        conductor: The conductor instance

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If not found
    """
    deleted = conductor.tracker.delete_arrangement(arrangement_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement {arrangement_id} not found",
        )
    return {"status": "deleted", "id": arrangement_id}


@router.get("/arrangements/suggestion", response_model=ArrangementSuggestion | None)
async def get_arrangement_suggestion(
    conductor: Annotated[Conductor, Depends(get_conductor)],
    arrangement_type: str = "composition",
) -> ArrangementSuggestion | None:
    """Get a suggestion for saving a high-performing arrangement.

    Checks tracked executions and returns a suggestion if an arrangement
    meets the threshold for saving (3+ executions, 70%+ success rate,
    75%+ average confidence).

    Args:
        conductor: The conductor instance
        arrangement_type: Type to check (composition or loop)

    Returns:
        ArrangementSuggestion if one should be saved, None otherwise
    """
    # This would iterate through tracked arrangements and find one to suggest
    # For now, return None as suggestions are logged during execution
    return None


@router.post("/arrangements/from-task/{task_id}", response_model=SavedArrangement)
async def save_arrangement_from_task(
    task_id: str,
    name: str,
    description: str,
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    conductor: Annotated[Conductor, Depends(get_conductor)],
    auth: OptionalAuth = None,
) -> SavedArrangement:
    """Save the arrangement used for a successful task.

    Retrieves the task, extracts the arrangement that was used,
    and saves it for future reuse.

    Args:
        task_id: The task ID to save arrangement from
        name: Name for the saved arrangement
        description: Description of what it's good for
        db: The database client
        conductor: The conductor instance
        auth: Optional authentication context

    Returns:
        The saved arrangement

    Raises:
        HTTPException: If task not found or wasn't a novel arrangement
    """
    task_data = await db.get_task(task_id)
    if not task_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    # Check if it was a novel or loop execution
    response = task_data.get("response", {})
    instrument_used = response.get("metadata", {}).get("instrument_used", "")

    if not instrument_used.startswith(("novel:", "loop:")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task was not executed with a novel arrangement or loop",
        )

    # For now, we can't reconstruct the exact arrangement from the task
    # This would require storing the arrangement spec with the task
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Saving arrangements from completed tasks requires storing arrangement specs with tasks (future enhancement)",
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
# Trust Escalation Endpoints (Phase 3D)
# -------------------------------------------------------------------------


@router.get("/trust/metrics", response_model=TrustMetrics)
async def get_trust_metrics(
    auth: Auth,
    trust_tracker: Annotated[TrustTracker, Depends(get_trust_tracker)],
) -> TrustMetrics:
    """Get trust metrics for the current user/app.

    Returns execution counts, success rates, and current trust level.

    Args:
        auth: Authentication context (required)
        trust_tracker: The trust tracker instance

    Returns:
        TrustMetrics for the user/app
    """
    user_id = auth.user.id if auth.user else None
    return trust_tracker.get_metrics(auth.app.id, user_id)


@router.get("/trust/suggestion", response_model=TrustSuggestion | None)
async def get_trust_suggestion(
    auth: Auth,
    trust_tracker: Annotated[TrustTracker, Depends(get_trust_tracker)],
) -> TrustSuggestion | None:
    """Get a suggestion to upgrade trust level if warranted.

    Based on success patterns:
    - Level 0 -> 1: 5+ consecutive successes, 80%+ success rate
    - Level 1 -> 2: 10+ consecutive successes, 90%+ success rate

    Args:
        auth: Authentication context (required)
        trust_tracker: The trust tracker instance

    Returns:
        TrustSuggestion if upgrade is warranted, None otherwise
    """
    user_id = auth.user.id if auth.user else None
    return trust_tracker.get_suggestion(auth.app.id, user_id)


@router.put("/trust/level", response_model=TrustMetrics)
async def update_trust_level(
    update: TrustLevelUpdate,
    auth: Auth,
    trust_tracker: Annotated[TrustTracker, Depends(get_trust_tracker)],
) -> TrustMetrics:
    """Update the trust level for the current user/app.

    This is a user-initiated action to change their preferred trust level.
    The server stores this preference and uses it for future suggestions.

    Args:
        update: The new trust level (0, 1, or 2)
        auth: Authentication context (required)
        trust_tracker: The trust tracker instance

    Returns:
        Updated TrustMetrics
    """
    user_id = auth.user.id if auth.user else None
    return trust_tracker.update_trust_level(
        auth.app.id, update.trust_level, user_id
    )


# -------------------------------------------------------------------------
# Task Management Endpoints (Phase 3F: Semi-Autonomic Layer)
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


@router.get("/tasks/stats")
async def get_task_stats(
    task_manager: Annotated[TaskManager, Depends(get_task_manager)],
) -> dict:
    """Get task manager statistics.

    Returns:
        Dict with active_count, total_count
    """
    return {
        "active_count": task_manager.active_count,
        "total_count": task_manager.total_count,
    }


# =============================================================================
# Room Registry (Phase 4 - Multi-Room Architecture)
# =============================================================================

_room_registry: RoomRegistry | None = None


def get_room_registry() -> RoomRegistry:
    """Get or create the room registry singleton."""
    global _room_registry
    if _room_registry is None:
        _room_registry = RoomRegistry()
    return _room_registry


@router.post("/rooms/register")
async def register_room(
    registration: RoomRegistration,
    room_registry: Annotated[RoomRegistry, Depends(get_room_registry)],
) -> dict:
    """Register a room with the server.

    Called by Local Room, iOS Room, etc. when they come online.
    """
    room = room_registry.register(registration)
    return {
        "status": "registered",
        "room_id": room.room_id,
        "room_type": room.room_type,
    }


@router.post("/rooms/deregister")
async def deregister_room(
    data: dict,
    room_registry: Annotated[RoomRegistry, Depends(get_room_registry)],
) -> dict:
    """Deregister a room from the server.

    Called when a room is shutting down gracefully.
    """
    room_id = data.get("room_id")
    if not room_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="room_id is required",
        )

    found = room_registry.deregister(room_id)
    return {
        "status": "deregistered" if found else "not_found",
        "room_id": room_id,
    }


@router.post("/rooms/heartbeat")
async def room_heartbeat(
    heartbeat: RoomHeartbeat,
    room_registry: Annotated[RoomRegistry, Depends(get_room_registry)],
) -> dict:
    """Process a heartbeat from a room.

    Rooms should send heartbeats periodically to indicate they're still online.
    """
    found = room_registry.heartbeat(heartbeat)

    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room not found: {heartbeat.room_id}. Please re-register.",
        )

    return {"status": "ok", "room_id": heartbeat.room_id}


@router.get("/rooms")
async def list_rooms(
    room_registry: Annotated[RoomRegistry, Depends(get_room_registry)],
) -> dict:
    """List all registered rooms."""
    rooms = room_registry.get_all_rooms()
    return {
        "rooms": [
            {
                "room_id": r.room_id,
                "room_name": r.room_name,
                "room_type": r.room_type,
                "url": r.url,
                "status": r.status,
                "capabilities": list(r.capabilities),
                "instruments": r.instruments,
                "last_heartbeat": r.last_heartbeat.isoformat(),
            }
            for r in rooms
        ],
        "stats": room_registry.stats(),
    }


@router.get("/rooms/{room_id}")
async def get_room(
    room_id: str,
    room_registry: Annotated[RoomRegistry, Depends(get_room_registry)],
) -> dict:
    """Get details for a specific room."""
    room = room_registry.get_room(room_id)

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room not found: {room_id}",
        )

    return {
        "room_id": room.room_id,
        "room_name": room.room_name,
        "room_type": room.room_type,
        "url": room.url,
        "status": room.status,
        "capabilities": list(room.capabilities),
        "instruments": room.instruments,
        "last_heartbeat": room.last_heartbeat.isoformat(),
        "registered_at": room.registered_at.isoformat(),
    }
