"""Heartbeat worker - processes due heartbeats via the Librarian pipeline."""

import logging
from datetime import datetime, UTC, timedelta
from typing import Any

import httpx
from croniter import croniter

from conductors.reference.general_conductor import GeneralConductor
from librarian.catalog.planner import ArrangementPlanner
from loop_symphony.db.client import DatabaseClient
from loop_symphony.models.finding import ExecutionMetadata, Finding
from loop_symphony.models.heartbeat import Heartbeat, HeartbeatStatus
from loop_symphony.models.task import (
    TaskContext,
    TaskPreferences,
    TaskRequest,
    TaskResponse,
)

logger = logging.getLogger(__name__)


class HeartbeatWorker:
    """Processes due heartbeats using the Librarian pipeline.

    Flow: expand query template → Librarian plans instrument →
    execute instrument directly → store result → call webhook.
    """

    def __init__(
        self,
        db: DatabaseClient,
        conductor: GeneralConductor,
        planner: ArrangementPlanner | None = None,
    ) -> None:
        self.db = db
        self.conductor = conductor
        self.planner = planner

    def _is_heartbeat_due(
        self,
        heartbeat: Heartbeat,
        last_run_at: datetime | None,
    ) -> bool:
        """Check if a heartbeat is due to run."""
        try:
            now = datetime.now(UTC)
            cron = croniter(heartbeat.cron_expression, now)
            prev_scheduled = cron.get_prev(datetime)

            if prev_scheduled.tzinfo is None:
                prev_scheduled = prev_scheduled.replace(tzinfo=UTC)

            if last_run_at is None:
                time_since_scheduled = now - prev_scheduled
                return time_since_scheduled <= timedelta(minutes=5)

            return last_run_at < prev_scheduled

        except Exception as e:
            logger.error(f"Error checking cron for heartbeat {heartbeat.id}: {e}")
            return False

    def _expand_template(self, template: str, heartbeat: Heartbeat) -> str:
        """Expand placeholders in the query template."""
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
        """Call the webhook URL with the task result."""
        if not heartbeat.webhook_url:
            return True

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
        """Get when a heartbeat last ran successfully."""
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

    async def _execute_via_librarian(
        self, query: str, context: TaskContext,
    ) -> TaskResponse:
        """Execute a heartbeat query through the Librarian pipeline.

        1. Planner chooses instrument based on query
        2. Instrument executes directly (bypasses GeneralConductor routing)
        3. Returns TaskResponse
        """
        import time

        # Step 1: Let the planner choose the instrument
        if self.planner:
            plan = await self.planner.plan(query)
            instrument_name = (
                plan.proposal.instrument
                or (plan.proposal.steps[0].instrument if plan.proposal.steps else None)
                or "research"
            )
        else:
            # Fallback: use GeneralConductor's routing
            instrument_name = await self.conductor.route(
                TaskRequest(query=query, context=context)
            )

        # Step 2: Execute the instrument directly
        instrument = self.conductor.instruments.get(instrument_name)
        if instrument is None:
            raise ValueError(f"Unknown instrument: {instrument_name}")

        start_time = time.time()
        result = await instrument.execute(query, context)
        duration_ms = int((time.time() - start_time) * 1000)

        # Step 3: Convert to TaskResponse
        server_findings = [
            Finding.model_validate(f.model_dump()) for f in (result.findings or [])
        ]

        return TaskResponse(
            request_id=f"heartbeat-{datetime.now(UTC).isoformat()}",
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

    async def process_heartbeat(self, heartbeat: Heartbeat) -> dict[str, Any]:
        """Process a single heartbeat via the Librarian pipeline."""
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

            # Execute via Librarian pipeline
            response = await self._execute_via_librarian(query, context)

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
        """Process all due heartbeats."""
        logger.info("Heartbeat tick starting")

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
