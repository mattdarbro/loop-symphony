"""Supabase database client for task persistence."""

import logging
from datetime import UTC, datetime
from typing import Any

from supabase import create_client, Client

from loop_symphony.config import get_settings
from loop_symphony.models.outcome import TaskStatus
from loop_symphony.models.task import TaskRequest, TaskResponse

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Client for Supabase database operations."""

    def __init__(self) -> None:
        settings = get_settings()
        self.client: Client = create_client(
            settings.supabase_url,
            settings.supabase_key,
        )

    async def create_task(self, request: TaskRequest) -> str:
        """Create a new task in the database.

        Args:
            request: The task request

        Returns:
            The task ID
        """
        data = {
            "id": request.id,
            "request": request.model_dump(mode="json"),
            "status": TaskStatus.PENDING.value,
        }

        result = self.client.table("tasks").insert(data).execute()
        logger.debug(f"Created task {request.id}")
        return request.id

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        error: str | None = None,
    ) -> None:
        """Update task status.

        Args:
            task_id: The task ID
            status: New status
            error: Optional error message
        """
        data: dict[str, Any] = {"status": status.value}
        if error:
            data["error"] = error

        self.client.table("tasks").update(data).eq("id", task_id).execute()
        logger.debug(f"Updated task {task_id} status to {status.value}")

    async def complete_task(
        self,
        task_id: str,
        response: TaskResponse,
    ) -> None:
        """Mark task as complete with response.

        Args:
            task_id: The task ID
            response: The task response
        """
        data = {
            "status": TaskStatus.COMPLETE.value,
            "outcome": response.outcome.value,
            "response": response.model_dump(mode="json"),
            "completed_at": datetime.now(UTC).isoformat(),
        }

        self.client.table("tasks").update(data).eq("id", task_id).execute()
        logger.debug(f"Completed task {task_id} with outcome {response.outcome.value}")

    async def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed.

        Args:
            task_id: The task ID
            error: Error message
        """
        data = {
            "status": TaskStatus.FAILED.value,
            "error": error,
            "completed_at": datetime.now(UTC).isoformat(),
        }

        self.client.table("tasks").update(data).eq("id", task_id).execute()
        logger.debug(f"Failed task {task_id}: {error}")

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID.

        Args:
            task_id: The task ID

        Returns:
            Task data or None if not found
        """
        result = (
            self.client.table("tasks")
            .select("*")
            .eq("id", task_id)
            .execute()
        )

        if result.data:
            return result.data[0]
        return None

    async def record_iteration(
        self,
        task_id: str,
        iteration_num: int,
        phase: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        duration_ms: int,
    ) -> None:
        """Record a task iteration for debugging.

        Args:
            task_id: The task ID
            iteration_num: Iteration number
            phase: Phase name (problem, hypothesis, test, analysis, reflection)
            input_data: Input to the phase
            output_data: Output from the phase
            duration_ms: Duration in milliseconds
        """
        data = {
            "task_id": task_id,
            "iteration_num": iteration_num,
            "phase": phase,
            "input": input_data,
            "output": output_data,
            "duration_ms": duration_ms,
        }

        self.client.table("task_iterations").insert(data).execute()
        logger.debug(f"Recorded iteration {iteration_num}/{phase} for task {task_id}")

    async def get_task_iterations(self, task_id: str) -> list[dict[str, Any]]:
        """Get all iterations for a task.

        Args:
            task_id: The task ID

        Returns:
            List of iteration records
        """
        result = (
            self.client.table("task_iterations")
            .select("*")
            .eq("task_id", task_id)
            .order("iteration_num")
            .order("created_at")
            .execute()
        )

        return result.data
