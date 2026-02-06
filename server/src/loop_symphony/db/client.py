"""Supabase database client for task persistence."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from supabase import create_client, Client

from loop_symphony.config import get_settings
from loop_symphony.models.heartbeat import (
    Heartbeat,
    HeartbeatCreate,
    HeartbeatRun,
    HeartbeatUpdate,
)
from loop_symphony.models.identity import App, UserProfile
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

    # -------------------------------------------------------------------------
    # Identity methods
    # -------------------------------------------------------------------------

    async def get_app_by_api_key(self, api_key: str) -> App | None:
        """Look up app by API key.

        Args:
            api_key: The API key to look up

        Returns:
            App if found, None otherwise
        """
        result = (
            self.client.table("apps")
            .select("*")
            .eq("api_key", api_key)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return App(**result.data[0])
        return None

    async def get_or_create_user_profile(
        self,
        app_id: UUID,
        external_user_id: str,
    ) -> UserProfile:
        """Get existing user profile or create new one.

        Args:
            app_id: The app ID
            external_user_id: The external user ID from the iOS app

        Returns:
            The user profile
        """
        # Try to find existing profile
        result = (
            self.client.table("user_profiles")
            .select("*")
            .eq("app_id", str(app_id))
            .eq("external_user_id", external_user_id)
            .execute()
        )

        if result.data and len(result.data) > 0:
            return UserProfile(**result.data[0])

        # Create new profile
        new_profile = (
            self.client.table("user_profiles")
            .insert({
                "app_id": str(app_id),
                "external_user_id": external_user_id,
            })
            .execute()
        )
        return UserProfile(**new_profile.data[0])

    async def update_user_last_seen(self, user_id: UUID) -> None:
        """Update user's last_seen_at timestamp.

        Args:
            user_id: The user profile ID
        """
        self.client.table("user_profiles").update({
            "last_seen_at": datetime.now(UTC).isoformat(),
        }).eq("id", str(user_id)).execute()

    # -------------------------------------------------------------------------
    # Heartbeat methods
    # -------------------------------------------------------------------------

    async def create_heartbeat(
        self,
        app_id: UUID,
        user_id: UUID | None,
        data: HeartbeatCreate,
    ) -> Heartbeat:
        """Create a new heartbeat.

        Args:
            app_id: The app ID
            user_id: Optional user ID (None for app-wide heartbeats)
            data: The heartbeat creation data

        Returns:
            The created heartbeat
        """
        insert_data = {
            "app_id": str(app_id),
            "user_id": str(user_id) if user_id else None,
            **data.model_dump(),
        }
        result = self.client.table("heartbeats").insert(insert_data).execute()
        return Heartbeat(**result.data[0])

    async def list_heartbeats(
        self,
        app_id: UUID,
        user_id: UUID | None = None,
    ) -> list[Heartbeat]:
        """List heartbeats for an app/user.

        Args:
            app_id: The app ID
            user_id: Optional user ID to filter by

        Returns:
            List of heartbeats
        """
        query = (
            self.client.table("heartbeats")
            .select("*")
            .eq("app_id", str(app_id))
        )
        if user_id:
            query = query.eq("user_id", str(user_id))
        result = query.order("created_at", desc=True).execute()
        return [Heartbeat(**row) for row in result.data]

    async def get_heartbeat(
        self,
        heartbeat_id: UUID,
        app_id: UUID,
    ) -> Heartbeat | None:
        """Get a specific heartbeat (with app_id check for isolation).

        Args:
            heartbeat_id: The heartbeat ID
            app_id: The app ID (for isolation check)

        Returns:
            Heartbeat if found, None otherwise
        """
        result = (
            self.client.table("heartbeats")
            .select("*")
            .eq("id", str(heartbeat_id))
            .eq("app_id", str(app_id))
            .execute()
        )
        if result.data and len(result.data) > 0:
            return Heartbeat(**result.data[0])
        return None

    async def get_heartbeat_by_id(self, heartbeat_id: UUID) -> Heartbeat | None:
        """Get a heartbeat by ID (no app isolation check).

        Args:
            heartbeat_id: The heartbeat ID

        Returns:
            Heartbeat if found, None otherwise
        """
        result = (
            self.client.table("heartbeats")
            .select("*")
            .eq("id", str(heartbeat_id))
            .execute()
        )
        if result.data and len(result.data) > 0:
            return Heartbeat(**result.data[0])
        return None

    async def update_heartbeat(
        self,
        heartbeat_id: UUID,
        app_id: UUID,
        updates: HeartbeatUpdate,
    ) -> Heartbeat | None:
        """Update a heartbeat.

        Args:
            heartbeat_id: The heartbeat ID
            app_id: The app ID (for isolation check)
            updates: The fields to update

        Returns:
            Updated heartbeat if found, None otherwise
        """
        update_data = updates.model_dump(exclude_none=True)
        update_data["updated_at"] = datetime.now(UTC).isoformat()

        result = (
            self.client.table("heartbeats")
            .update(update_data)
            .eq("id", str(heartbeat_id))
            .eq("app_id", str(app_id))
            .execute()
        )
        if result.data:
            return Heartbeat(**result.data[0])
        return None

    async def delete_heartbeat(self, heartbeat_id: UUID, app_id: UUID) -> bool:
        """Delete a heartbeat.

        Args:
            heartbeat_id: The heartbeat ID
            app_id: The app ID (for isolation check)

        Returns:
            True if deleted, False if not found
        """
        result = (
            self.client.table("heartbeats")
            .delete()
            .eq("id", str(heartbeat_id))
            .eq("app_id", str(app_id))
            .execute()
        )
        return len(result.data) > 0

    async def get_pending_heartbeat_runs(self) -> list[HeartbeatRun]:
        """Get pending heartbeat runs for processing.

        Returns:
            List of pending heartbeat runs
        """
        result = (
            self.client.table("heartbeat_runs")
            .select("*")
            .eq("status", "pending")
            .order("created_at")
            .execute()
        )
        return [HeartbeatRun(**row) for row in result.data]

    async def update_heartbeat_run(
        self,
        run_id: UUID,
        updates: dict[str, Any],
    ) -> None:
        """Update a heartbeat run status.

        Args:
            run_id: The heartbeat run ID
            updates: Fields to update
        """
        self.client.table("heartbeat_runs").update(updates).eq(
            "id", str(run_id)
        ).execute()

    # -------------------------------------------------------------------------
    # Saved Arrangement methods (Phase 3C: Meta-Learning)
    # -------------------------------------------------------------------------

    async def create_saved_arrangement(
        self,
        arrangement_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a saved arrangement.

        Args:
            arrangement_data: The arrangement data to save

        Returns:
            The created arrangement record
        """
        result = (
            self.client.table("saved_arrangements")
            .insert(arrangement_data)
            .execute()
        )
        return result.data[0]

    async def list_saved_arrangements(
        self,
        app_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """List saved arrangements.

        Args:
            app_id: Optional app ID to filter by (includes global arrangements)

        Returns:
            List of saved arrangement records
        """
        query = (
            self.client.table("saved_arrangements")
            .select("*")
            .eq("is_active", True)
        )

        if app_id is not None:
            # Include global (app_id is null) and app-specific
            query = query.or_(f"app_id.is.null,app_id.eq.{app_id}")

        result = query.order("created_at", desc=True).execute()
        return result.data

    async def get_saved_arrangement(
        self,
        arrangement_id: UUID,
    ) -> dict[str, Any] | None:
        """Get a saved arrangement by ID.

        Args:
            arrangement_id: The arrangement ID

        Returns:
            The arrangement record or None
        """
        result = (
            self.client.table("saved_arrangements")
            .select("*")
            .eq("id", str(arrangement_id))
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    async def get_saved_arrangement_by_name(
        self,
        name: str,
        app_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        """Get a saved arrangement by name.

        Args:
            name: The arrangement name
            app_id: Optional app ID

        Returns:
            The arrangement record or None
        """
        query = (
            self.client.table("saved_arrangements")
            .select("*")
            .eq("name", name)
            .eq("is_active", True)
        )

        if app_id is not None:
            query = query.or_(f"app_id.is.null,app_id.eq.{app_id}")

        result = query.execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    async def update_saved_arrangement(
        self,
        arrangement_id: UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update a saved arrangement.

        Args:
            arrangement_id: The arrangement ID
            updates: Fields to update

        Returns:
            The updated arrangement or None
        """
        updates["updated_at"] = datetime.now(UTC).isoformat()
        result = (
            self.client.table("saved_arrangements")
            .update(updates)
            .eq("id", str(arrangement_id))
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    async def delete_saved_arrangement(
        self,
        arrangement_id: UUID,
    ) -> bool:
        """Delete (soft-delete) a saved arrangement.

        Args:
            arrangement_id: The arrangement ID

        Returns:
            True if deleted, False if not found
        """
        result = (
            self.client.table("saved_arrangements")
            .update({"is_active": False, "updated_at": datetime.now(UTC).isoformat()})
            .eq("id", str(arrangement_id))
            .execute()
        )
        return len(result.data) > 0

    async def update_arrangement_stats(
        self,
        arrangement_id: UUID,
        stats: dict[str, Any],
    ) -> None:
        """Update arrangement statistics.

        Args:
            arrangement_id: The arrangement ID
            stats: The stats to update
        """
        self.client.table("saved_arrangements").update({
            "stats": stats,
            "updated_at": datetime.now(UTC).isoformat(),
        }).eq("id", str(arrangement_id)).execute()

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Check database connectivity and return health status.

        Performs a simple query to verify the database is reachable.

        Returns:
            Dict with:
                - healthy: bool - whether the database is reachable
                - latency_ms: float - query latency in milliseconds
                - error: str | None - error message if unhealthy
        """
        import time

        start = time.perf_counter()
        try:
            # Simple query to verify connectivity
            # Using a lightweight query that should always work
            result = self.client.table("tasks").select("id").limit(1).execute()
            latency_ms = (time.perf_counter() - start) * 1000

            return {
                "healthy": True,
                "latency_ms": round(latency_ms, 2),
                "error": None,
            }
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(f"Database health check failed: {e}")

            return {
                "healthy": False,
                "latency_ms": round(latency_ms, 2),
                "error": str(e),
            }
