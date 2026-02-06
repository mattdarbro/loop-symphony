"""Task manager for semi-autonomic process control (Phase 3F).

Tracks active background tasks and provides:
- Query what tasks are currently running
- Cancel or redirect running tasks
- Task lifecycle management
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    """State of a managed task."""

    QUEUED = "queued"  # Waiting to start
    RUNNING = "running"  # Currently executing
    CANCELLING = "cancelling"  # Cancel requested, waiting for cleanup
    CANCELLED = "cancelled"  # Successfully cancelled
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Finished with error


@dataclass
class ManagedTask:
    """A task being tracked by the TaskManager."""

    task_id: str
    query: str
    instrument: str | None = None
    asyncio_task: asyncio.Task | None = None
    state: TaskState = TaskState.QUEUED
    started_at: datetime | None = None
    progress: str | None = None
    current_iteration: int = 0
    max_iterations: int | None = None
    app_id: str | None = None
    user_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "task_id": self.task_id,
            "query": self.query[:100] + "..." if len(self.query) > 100 else self.query,
            "instrument": self.instrument,
            "state": self.state.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "progress": self.progress,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "app_id": self.app_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "running_seconds": (
                (datetime.now(UTC) - self.started_at).total_seconds()
                if self.started_at
                else None
            ),
        }


class TaskManager:
    """Manages background task lifecycle.

    Provides visibility into what the system is working on and
    allows users to cancel or query running tasks.

    This implements the "semi-autonomic" pattern where tasks run
    automatically but can be observed and controlled by the user.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ManagedTask] = {}
        self._lock = asyncio.Lock()

    async def register_task(
        self,
        task_id: str,
        query: str,
        instrument: str | None = None,
        app_id: str | None = None,
        user_id: str | None = None,
    ) -> ManagedTask:
        """Register a new task before execution starts.

        Args:
            task_id: Unique task identifier
            query: The user's query
            instrument: The instrument that will handle it
            app_id: Optional app ID for multi-tenant tracking
            user_id: Optional user ID

        Returns:
            The ManagedTask instance
        """
        async with self._lock:
            managed = ManagedTask(
                task_id=task_id,
                query=query,
                instrument=instrument,
                app_id=app_id,
                user_id=user_id,
            )
            self._tasks[task_id] = managed
            logger.debug(f"Registered task {task_id}")
            return managed

    async def start_task(
        self,
        task_id: str,
        asyncio_task: asyncio.Task,
        max_iterations: int | None = None,
    ) -> None:
        """Mark a task as started with its asyncio.Task handle.

        Args:
            task_id: The task identifier
            asyncio_task: The asyncio.Task running the work
            max_iterations: Expected max iterations (for progress)
        """
        async with self._lock:
            if task_id in self._tasks:
                managed = self._tasks[task_id]
                managed.asyncio_task = asyncio_task
                managed.state = TaskState.RUNNING
                managed.started_at = datetime.now(UTC)
                managed.max_iterations = max_iterations
                logger.debug(f"Started task {task_id}")

    async def update_progress(
        self,
        task_id: str,
        iteration: int,
        progress: str | None = None,
    ) -> None:
        """Update task progress during execution.

        Args:
            task_id: The task identifier
            iteration: Current iteration number
            progress: Optional progress message
        """
        async with self._lock:
            if task_id in self._tasks:
                managed = self._tasks[task_id]
                managed.current_iteration = iteration
                if progress:
                    managed.progress = progress

    async def complete_task(self, task_id: str) -> None:
        """Mark a task as completed."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].state = TaskState.COMPLETED
                self._tasks[task_id].asyncio_task = None
                logger.debug(f"Completed task {task_id}")

    async def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].state = TaskState.FAILED
                self._tasks[task_id].progress = f"Error: {error}"
                self._tasks[task_id].asyncio_task = None
                logger.debug(f"Failed task {task_id}: {error}")

    async def cancel_task(self, task_id: str) -> bool:
        """Request cancellation of a running task.

        Args:
            task_id: The task to cancel

        Returns:
            True if cancellation was initiated, False if task not found or not running
        """
        async with self._lock:
            if task_id not in self._tasks:
                return False

            managed = self._tasks[task_id]

            if managed.state != TaskState.RUNNING:
                return False

            if managed.asyncio_task is None:
                return False

            # Request cancellation
            managed.state = TaskState.CANCELLING
            managed.asyncio_task.cancel()
            logger.info(f"Requested cancellation of task {task_id}")
            return True

    async def mark_cancelled(self, task_id: str) -> None:
        """Mark a task as successfully cancelled (after cleanup)."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].state = TaskState.CANCELLED
                self._tasks[task_id].asyncio_task = None
                logger.debug(f"Task {task_id} cancelled")

    def get_task(self, task_id: str) -> ManagedTask | None:
        """Get info about a specific task."""
        return self._tasks.get(task_id)

    def get_active_tasks(
        self,
        app_id: str | None = None,
        user_id: str | None = None,
    ) -> list[ManagedTask]:
        """Get all currently active (running or queued) tasks.

        Args:
            app_id: Filter by app ID
            user_id: Filter by user ID

        Returns:
            List of active ManagedTask instances
        """
        active_states = {TaskState.QUEUED, TaskState.RUNNING, TaskState.CANCELLING}
        tasks = [
            t for t in self._tasks.values()
            if t.state in active_states
        ]

        if app_id:
            tasks = [t for t in tasks if t.app_id == app_id]
        if user_id:
            tasks = [t for t in tasks if t.user_id == user_id]

        return tasks

    def get_all_tasks(
        self,
        limit: int = 100,
        app_id: str | None = None,
    ) -> list[ManagedTask]:
        """Get recent tasks (for debugging/monitoring).

        Args:
            limit: Maximum number of tasks to return
            app_id: Filter by app ID

        Returns:
            List of ManagedTask instances, most recent first
        """
        tasks = list(self._tasks.values())

        if app_id:
            tasks = [t for t in tasks if t.app_id == app_id]

        # Sort by created_at descending
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    async def cleanup_old_tasks(self, max_age_seconds: int = 3600) -> int:
        """Remove completed/failed/cancelled tasks older than max_age.

        Args:
            max_age_seconds: Maximum age in seconds before cleanup

        Returns:
            Number of tasks cleaned up
        """
        async with self._lock:
            now = datetime.now(UTC)
            terminal_states = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
            to_remove = []

            for task_id, managed in self._tasks.items():
                if managed.state in terminal_states:
                    age = (now - managed.created_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(task_id)

            for task_id in to_remove:
                del self._tasks[task_id]

            if to_remove:
                logger.debug(f"Cleaned up {len(to_remove)} old tasks")

            return len(to_remove)

    @property
    def active_count(self) -> int:
        """Number of currently active tasks."""
        active_states = {TaskState.QUEUED, TaskState.RUNNING, TaskState.CANCELLING}
        return sum(1 for t in self._tasks.values() if t.state in active_states)

    @property
    def total_count(self) -> int:
        """Total number of tracked tasks."""
        return len(self._tasks)
