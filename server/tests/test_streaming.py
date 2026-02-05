"""Tests for SSE streaming support."""

import asyncio
import json
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.api.events import (
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_ITERATION,
    EVENT_STARTED,
    EventBus,
)


# ---------------------------------------------------------------------------
# TestEventBusEmit
# ---------------------------------------------------------------------------

class TestEventBusEmit:
    """Verify EventBus.emit() behavior."""

    def test_emit_stores_in_history(self):
        """Emitted events are stored in history."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})

        assert len(bus._events["t1"]) == 1
        assert bus._events["t1"][0]["event"] == EVENT_STARTED

    def test_emit_adds_timestamp(self):
        """Emitted events get a timestamp field."""
        bus = EventBus()
        before = time.time()
        bus.emit("t1", {"event": EVENT_STARTED})
        after = time.time()

        event = bus._events["t1"][0]
        assert before <= event["timestamp"] <= after

    def test_emit_adds_task_id(self):
        """Emitted events get the task_id stamped on them."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})

        assert bus._events["t1"][0]["task_id"] == "t1"

    def test_emit_does_not_mutate_original(self):
        """Original event dict is not mutated."""
        bus = EventBus()
        original = {"event": EVENT_STARTED}
        bus.emit("t1", original)

        assert "task_id" not in original
        assert "timestamp" not in original

    def test_multiple_events_stored_in_order(self):
        """Events are appended in emission order."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})
        bus.emit("t1", {"event": EVENT_ITERATION, "iteration_num": 1})
        bus.emit("t1", {"event": EVENT_COMPLETE})

        events = bus._events["t1"]
        assert len(events) == 3
        assert events[0]["event"] == EVENT_STARTED
        assert events[1]["event"] == EVENT_ITERATION
        assert events[2]["event"] == EVENT_COMPLETE

    def test_different_tasks_isolated(self):
        """Events for different tasks are stored separately."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})
        bus.emit("t2", {"event": EVENT_STARTED})

        assert len(bus._events["t1"]) == 1
        assert len(bus._events["t2"]) == 1
        assert bus._events["t1"][0]["task_id"] == "t1"
        assert bus._events["t2"][0]["task_id"] == "t2"


# ---------------------------------------------------------------------------
# TestEventBusSubscribe
# ---------------------------------------------------------------------------

class TestEventBusSubscribe:
    """Verify EventBus.subscribe() and queue delivery."""

    @pytest.mark.asyncio
    async def test_subscriber_receives_emitted_events(self):
        """Subscriber receives events emitted after subscription."""
        bus = EventBus()
        queue = bus.subscribe("t1")

        bus.emit("t1", {"event": EVENT_STARTED})

        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["event"] == EVENT_STARTED

    @pytest.mark.asyncio
    async def test_late_joiner_gets_history(self):
        """Subscriber created after emit gets full history."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})
        bus.emit("t1", {"event": EVENT_ITERATION, "iteration_num": 1})

        queue = bus.subscribe("t1")

        event1 = await asyncio.wait_for(queue.get(), timeout=1.0)
        event2 = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event1["event"] == EVENT_STARTED
        assert event2["event"] == EVENT_ITERATION

    @pytest.mark.asyncio
    async def test_late_joiner_gets_history_then_live(self):
        """Late joiner receives history, then live events in order."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})

        queue = bus.subscribe("t1")

        # Get history event
        hist = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert hist["event"] == EVENT_STARTED

        # Now emit a live event
        bus.emit("t1", {"event": EVENT_COMPLETE})
        live = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert live["event"] == EVENT_COMPLETE

    @pytest.mark.asyncio
    async def test_multiple_subscribers_each_receive(self):
        """Multiple subscribers each get a copy of events."""
        bus = EventBus()
        q1 = bus.subscribe("t1")
        q2 = bus.subscribe("t1")

        bus.emit("t1", {"event": EVENT_STARTED})

        e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert e1["event"] == EVENT_STARTED
        assert e2["event"] == EVENT_STARTED

    def test_unsubscribe_removes_queue(self):
        """Unsubscribe removes the queue from subscriber list."""
        bus = EventBus()
        queue = bus.subscribe("t1")
        assert len(bus._subscribers["t1"]) == 1

        bus.unsubscribe("t1", queue)
        assert len(bus._subscribers["t1"]) == 0

    def test_unsubscribe_is_idempotent(self):
        """Unsubscribing twice does not raise."""
        bus = EventBus()
        queue = bus.subscribe("t1")
        bus.unsubscribe("t1", queue)
        bus.unsubscribe("t1", queue)  # Should not raise


# ---------------------------------------------------------------------------
# TestEventBusTerminal
# ---------------------------------------------------------------------------

class TestEventBusTerminal:
    """Verify has_terminal_event() behavior."""

    def test_false_initially(self):
        """No terminal event initially."""
        bus = EventBus()
        assert not bus.has_terminal_event("t1")

    def test_false_after_started(self):
        """STARTED is not a terminal event."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})
        assert not bus.has_terminal_event("t1")

    def test_true_after_complete(self):
        """COMPLETE is a terminal event."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_COMPLETE})
        assert bus.has_terminal_event("t1")

    def test_true_after_error(self):
        """ERROR is a terminal event."""
        bus = EventBus()
        bus.emit("t1", {"event": EVENT_ERROR, "error": "boom"})
        assert bus.has_terminal_event("t1")


# ---------------------------------------------------------------------------
# TestEventBusCleanup
# ---------------------------------------------------------------------------

class TestEventBusCleanup:
    """Verify cleanup_stale() behavior."""

    def test_cleanup_removes_expired(self):
        """Cleanup removes tasks past TTL."""
        bus = EventBus(history_ttl=0)  # Immediate expiry
        bus.emit("t1", {"event": EVENT_COMPLETE})
        # Manually set completion time in the past
        bus._completed_at["t1"] = time.monotonic() - 1

        removed = bus.cleanup_stale()

        assert removed == 1
        assert "t1" not in bus._events
        assert "t1" not in bus._subscribers
        assert "t1" not in bus._completed_at

    def test_cleanup_preserves_active(self):
        """Cleanup does not remove non-terminal tasks."""
        bus = EventBus(history_ttl=300)
        bus.emit("t1", {"event": EVENT_STARTED})

        removed = bus.cleanup_stale()

        assert removed == 0
        assert "t1" in bus._events

    def test_cleanup_preserves_recent_completed(self):
        """Cleanup does not remove recently completed tasks."""
        bus = EventBus(history_ttl=300)
        bus.emit("t1", {"event": EVENT_COMPLETE})

        removed = bus.cleanup_stale()

        assert removed == 0


# ---------------------------------------------------------------------------
# TestStreamEndpoint
# ---------------------------------------------------------------------------

class TestStreamEndpoint:
    """Verify GET /task/{id}/stream SSE endpoint."""

    @pytest.mark.asyncio
    async def test_returns_event_stream_content_type(self):
        """Stream endpoint returns text/event-stream content type."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value={"id": "t1", "status": "running"})
        routes._db_client = mock_db

        bus = EventBus()
        bus.emit("t1", {"event": EVENT_COMPLETE, "outcome": "complete"})
        routes._event_bus = bus

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/t1/stream")

            assert resp.headers["content-type"].startswith("text/event-stream")
        finally:
            routes._db_client = None
            routes._event_bus = None

    @pytest.mark.asyncio
    async def test_404_for_unknown_task(self):
        """Stream endpoint returns 404 for unknown task."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value=None)
        routes._db_client = mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/nonexistent/stream")

            assert resp.status_code == 404
        finally:
            routes._db_client = None

    @pytest.mark.asyncio
    async def test_delivers_events_in_sse_format(self):
        """Events are delivered in SSE data: {json} format."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value={"id": "t1", "status": "running"})
        routes._db_client = mock_db

        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})
        bus.emit("t1", {"event": EVENT_COMPLETE, "outcome": "complete"})
        routes._event_bus = bus

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/t1/stream")

            body = resp.text
            lines = [l for l in body.split("\n") if l.startswith("data:")]
            assert len(lines) == 2

            event1 = json.loads(lines[0].removeprefix("data: "))
            assert event1["event"] == EVENT_STARTED

            event2 = json.loads(lines[1].removeprefix("data: "))
            assert event2["event"] == EVENT_COMPLETE
        finally:
            routes._db_client = None
            routes._event_bus = None

    @pytest.mark.asyncio
    async def test_stream_terminates_on_complete(self):
        """Stream terminates after complete event."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value={"id": "t1", "status": "complete"})
        routes._db_client = mock_db

        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})
        bus.emit("t1", {"event": EVENT_COMPLETE, "outcome": "complete"})
        routes._event_bus = bus

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/t1/stream")

            # Response should be complete (not hanging)
            data_lines = [l for l in resp.text.split("\n") if l.startswith("data:")]
            last_event = json.loads(data_lines[-1].removeprefix("data: "))
            assert last_event["event"] == EVENT_COMPLETE
        finally:
            routes._db_client = None
            routes._event_bus = None

    @pytest.mark.asyncio
    async def test_stream_terminates_on_error(self):
        """Stream terminates after error event."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value={"id": "t1", "status": "failed"})
        routes._db_client = mock_db

        bus = EventBus()
        bus.emit("t1", {"event": EVENT_STARTED})
        bus.emit("t1", {"event": EVENT_ERROR, "error": "boom"})
        routes._event_bus = bus

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/t1/stream")

            data_lines = [l for l in resp.text.split("\n") if l.startswith("data:")]
            last_event = json.loads(data_lines[-1].removeprefix("data: "))
            assert last_event["event"] == EVENT_ERROR
        finally:
            routes._db_client = None
            routes._event_bus = None


# ---------------------------------------------------------------------------
# TestBackgroundTaskEmitsEvents
# ---------------------------------------------------------------------------

class TestBackgroundTaskEmitsEvents:
    """Verify execute_task_background emits events to the bus."""

    def _make_response(self):
        """Build a minimal TaskResponse."""
        from loop_symphony.models.finding import Finding, ExecutionMetadata
        from loop_symphony.models.outcome import Outcome
        from loop_symphony.models.task import TaskResponse

        return TaskResponse(
            request_id="t1",
            outcome=Outcome.COMPLETE,
            findings=[Finding(content="Answer")],
            summary="Done",
            confidence=0.9,
            metadata=ExecutionMetadata(
                instrument_used="note",
                iterations=1,
                duration_ms=0,
            ),
        )

    @pytest.mark.asyncio
    async def test_emits_started_and_complete_on_success(self):
        """Successful execution emits started and complete events."""
        from loop_symphony.api import routes
        from loop_symphony.models.task import TaskRequest

        mock_db = MagicMock()
        mock_db.update_task_status = AsyncMock()
        mock_db.complete_task = AsyncMock()

        response = self._make_response()
        mock_conductor = MagicMock()
        mock_conductor.execute = AsyncMock(return_value=response)

        bus = EventBus()
        request = TaskRequest(query="Test")
        await routes.execute_task_background(request, mock_conductor, mock_db, bus)

        events = bus._events[request.id]
        assert events[0]["event"] == EVENT_STARTED
        assert events[-1]["event"] == EVENT_COMPLETE
        assert events[-1]["outcome"] == "complete"
        assert events[-1]["summary"] == "Done"

    @pytest.mark.asyncio
    async def test_emits_started_and_error_on_failure(self):
        """Failed execution emits started and error events."""
        from loop_symphony.api import routes
        from loop_symphony.models.task import TaskRequest

        mock_db = MagicMock()
        mock_db.update_task_status = AsyncMock()
        mock_db.fail_task = AsyncMock()

        mock_conductor = MagicMock()
        mock_conductor.execute = AsyncMock(side_effect=RuntimeError("Boom"))

        bus = EventBus()
        request = TaskRequest(query="Test")
        await routes.execute_task_background(request, mock_conductor, mock_db, bus)

        events = bus._events[request.id]
        assert events[0]["event"] == EVENT_STARTED
        assert events[-1]["event"] == EVENT_ERROR
        assert events[-1]["error"] == "Boom"

    @pytest.mark.asyncio
    async def test_checkpoint_emits_iteration_events(self):
        """Checkpoint callback emits iteration events to bus."""
        from loop_symphony.api import routes
        from loop_symphony.models.task import TaskRequest

        mock_db = MagicMock()
        mock_db.update_task_status = AsyncMock()
        mock_db.complete_task = AsyncMock()
        mock_db.record_iteration = AsyncMock()

        async def call_checkpoint(request):
            fn = request.context.checkpoint_fn
            await fn(1, "iteration", {"q": "test"}, {"confidence": 0.8}, 100)
            return self._make_response()

        mock_conductor = MagicMock()
        mock_conductor.execute = call_checkpoint

        bus = EventBus()
        request = TaskRequest(query="Test")
        await routes.execute_task_background(request, mock_conductor, mock_db, bus)

        events = bus._events[request.id]
        iteration_events = [e for e in events if e["event"] == EVENT_ITERATION]
        assert len(iteration_events) == 1
        assert iteration_events[0]["iteration_num"] == 1
        assert iteration_events[0]["phase"] == "iteration"
        assert iteration_events[0]["duration_ms"] == 100

    @pytest.mark.asyncio
    async def test_db_write_still_happens_alongside_events(self):
        """DB record_iteration is still called alongside event emission."""
        from loop_symphony.api import routes
        from loop_symphony.models.task import TaskRequest

        mock_db = MagicMock()
        mock_db.update_task_status = AsyncMock()
        mock_db.complete_task = AsyncMock()
        mock_db.record_iteration = AsyncMock()

        async def call_checkpoint(request):
            fn = request.context.checkpoint_fn
            await fn(1, "iteration", {"q": "test"}, {"c": 0.8}, 100)
            return self._make_response()

        mock_conductor = MagicMock()
        mock_conductor.execute = call_checkpoint

        bus = EventBus()
        request = TaskRequest(query="Test")
        await routes.execute_task_background(request, mock_conductor, mock_db, bus)

        mock_db.record_iteration.assert_called_once_with(
            request.id, 1, "iteration", {"q": "test"}, {"c": 0.8}, 100
        )
