"""Heartbeat worker - processes due heartbeats."""

import logging
from datetime import datetime, UTC, timedelta
from typing import Any

import httpx
from croniter import croniter

from loop_symphony.db.client import DatabaseClient
from loop_symphony.manager.conductor import Conductor
from loop_symphony.models.heartbeat import Heartbeat, HeartbeatStatus
from loop_symphony.models.task import TaskContext, TaskRequest, TaskResponse

logger = logging.getLogger(__name__)


class HeartbeatWorker:
    """Processes due heartbeats and executes their tasks."""

    def __init__(
        self,
        db: DatabaseClient,
        conductor: Conductor,
    ) -> None:
        self.db = db
        self.conductor = conductor

    def _is_heartbeat_due(
        self,
        heartbeat: Heartbeat,
        last_run_at: datetime | None,
    ) -> bool:
        """Check if a heartbeat is due to run.

        Args:
            heartbeat: The heartbeat to check
            last_run_at: When the heartbeat last ran (None if never)

        Returns:
            True if the heartbeat should run now
        """
        try:
            # Use croniter to find the previous scheduled time
            now = datetime.now(UTC)
            cron = croniter(heartbeat.cron_expression, now)
            prev_scheduled = cron.get_prev(datetime)

            # Make prev_scheduled timezone-aware
            if prev_scheduled.tzinfo is None:
                prev_scheduled = prev_scheduled.replace(tzinfo=UTC)

            # If never run, check if we're within 5 minutes of a scheduled time
            if last_run_at is None:
                time_since_scheduled = now - prev_scheduled
                return time_since_scheduled <= timedelta(minutes=5)

            # If last run was before the previous scheduled time, it's due
            return last_run_at < prev_scheduled

        except Exception as e:
            logger.error(f"Error checking cron for heartbeat {heartbeat.id}: {e}")
            return False

    def _expand_template(self, template: str, heartbeat: Heartbeat) -> str:
        """Expand placeholders in the query template.

        Args:
            template: The query template with {placeholders}
            heartbeat: The heartbeat for context

        Returns:
            Expanded query string
        """
        now = datetime.now(UTC)
        return template.format(
            date=now.strftime("%Y-%m-%d"),
            datetime=now.isoformat(),
            time=now.strftime("%H:%M"),
            weekday=now.strftime("%A"),
            heartbeat_name=heartbeat.name,
        )

    async def _call_webhook(
        self,
        heartbeat: Heartbeat,
        response: TaskResponse,
        run_id: str,
    ) -> bool:
        """Call the webhook URL with the task result.

        Args:
            heartbeat: The heartbeat that triggered this
            response: The task response
            run_id: The heartbeat run ID

        Returns:
            True if webhook succeeded, False otherwise
        """
        if not heartbeat.webhook_url:
            return True  # No webhook configured, that's fine

        payload = {
            "event": "heartbeat.completed",
            "heartbeat_id": str(heartbeat.id),
            "heartbeat_name": heartbeat.name,
            "run_id": run_id,
            "task_id": response.request_id,
            "outcome": response.outcome.value,
            "confidence": response.confidence,
            "summary": response.summary,
            "findings": [f.model_dump() for f in response.findings],
            "suggested_followups": response.suggested_followups,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    heartbeat.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                logger.info(
                    f"Webhook called successfully for heartbeat {heartbeat.name}: "
                    f"status={resp.status_code}"
                )
                return True
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Webhook returned error for heartbeat {heartbeat.name}: "
                f"status={e.response.status_code}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Webhook failed for heartbeat {heartbeat.name}: {e}"
            )
            return False

    async def get_last_run_at(self, heartbeat_id) -> datetime | None:
        """Get when a heartbeat last ran successfully.

        Args:
            heartbeat_id: The heartbeat ID

        Returns:
            Datetime of last successful run, or None if never ran
        """
        result = (
            self.db.client.table("heartbeat_runs")
            .select("completed_at")
            .eq("heartbeat_id", str(heartbeat_id))
            .eq("status", HeartbeatStatus.COMPLETED.value)
            .order("completed_at", desc=True)
            .limit(1)
            .execute()
        )

        if result.data and len(result.data) > 0:
            completed_at = result.data[0]["completed_at"]
            if completed_at:
                return datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return None

    async def process_heartbeat(self, heartbeat: Heartbeat) -> dict[str, Any]:
        """Process a single heartbeat.

        Args:
            heartbeat: The heartbeat to process

        Returns:
            Dict with run details
        """
        run_id = None
        try:
            # Create a run record
            run_result = (
                self.db.client.table("heartbeat_runs")
                .insert({
                    "heartbeat_id": str(heartbeat.id),
                    "status": HeartbeatStatus.RUNNING.value,
                    "started_at": datetime.now(UTC).isoformat(),
                })
                .execute()
            )
            run_id = run_result.data[0]["id"]

            # Expand the query template
            query = self._expand_template(heartbeat.query_template, heartbeat)

            # Build context from template
            context = TaskContext(**heartbeat.context_template)

            # Execute the task
            request = TaskRequest(query=query, context=context)
            response = await self.conductor.execute(request)

            # Update run as completed
            self.db.client.table("heartbeat_runs").update({
                "status": HeartbeatStatus.COMPLETED.value,
                "completed_at": datetime.now(UTC).isoformat(),
                "task_id": response.request_id,
            }).eq("id", run_id).execute()

            logger.info(
                f"Heartbeat {heartbeat.name} completed: "
                f"outcome={response.outcome.value}, confidence={response.confidence}"
            )

            # Call webhook if configured
            webhook_success = await self._call_webhook(heartbeat, response, run_id)

            return {
                "heartbeat_id": str(heartbeat.id),
                "heartbeat_name": heartbeat.name,
                "run_id": run_id,
                "task_id": response.request_id,
                "status": "completed",
                "outcome": response.outcome.value,
                "summary": response.summary,
                "webhook_called": heartbeat.webhook_url is not None,
                "webhook_success": webhook_success,
            }

        except Exception as e:
            logger.error(f"Heartbeat {heartbeat.name} failed: {e}")

            if run_id:
                self.db.client.table("heartbeat_runs").update({
                    "status": HeartbeatStatus.FAILED.value,
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error_message": str(e),
                }).eq("id", run_id).execute()

            return {
                "heartbeat_id": str(heartbeat.id),
                "heartbeat_name": heartbeat.name,
                "run_id": run_id,
                "status": "failed",
                "error": str(e),
            }

    async def tick(self) -> dict[str, Any]:
        """Process all due heartbeats.

        Returns:
            Dict with summary of what was processed
        """
        logger.info("Heartbeat tick starting")

        # Get all active heartbeats
        result = (
            self.db.client.table("heartbeats")
            .select("*")
            .eq("is_active", True)
            .execute()
        )

        heartbeats = [Heartbeat(**row) for row in result.data]
        logger.info(f"Found {len(heartbeats)} active heartbeats")

        processed = []
        skipped = []

        for heartbeat in heartbeats:
            last_run = await self.get_last_run_at(heartbeat.id)

            if self._is_heartbeat_due(heartbeat, last_run):
                logger.info(f"Processing due heartbeat: {heartbeat.name}")
                run_result = await self.process_heartbeat(heartbeat)
                processed.append(run_result)
            else:
                skipped.append({
                    "heartbeat_id": str(heartbeat.id),
                    "heartbeat_name": heartbeat.name,
                    "reason": "not due yet",
                })

        logger.info(
            f"Heartbeat tick complete: {len(processed)} processed, {len(skipped)} skipped"
        )

        return {
            "processed": processed,
            "skipped": skipped,
            "total_active": len(heartbeats),
        }
