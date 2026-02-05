"""Tests for checkpoint emission and retrieval."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.models.task import TaskContext, TaskRequest


# ---------------------------------------------------------------------------
# TestCheckpointCallback
# ---------------------------------------------------------------------------

class TestCheckpointCallback:
    """Verify checkpoint_fn field on TaskContext."""

    def test_accepts_checkpoint_fn(self):
        """TaskContext accepts a checkpoint_fn."""
        fn = AsyncMock()
        ctx = TaskContext(checkpoint_fn=fn)
        assert ctx.checkpoint_fn is fn

    def test_excluded_from_serialization(self):
        """checkpoint_fn is not included in model_dump output."""
        fn = AsyncMock()
        ctx = TaskContext(checkpoint_fn=fn)
        dumped = ctx.model_dump(mode="json")

        assert "checkpoint_fn" not in dumped

    def test_preserved_through_model_copy(self):
        """checkpoint_fn survives model_copy()."""
        fn = AsyncMock()
        ctx = TaskContext(checkpoint_fn=fn, user_id="u1")
        copied = ctx.model_copy(update={"input_results": [{"x": 1}]})

        assert copied.checkpoint_fn is fn
        assert copied.user_id == "u1"
        assert copied.input_results == [{"x": 1}]

    def test_defaults_to_none(self):
        """checkpoint_fn defaults to None."""
        ctx = TaskContext()
        assert ctx.checkpoint_fn is None


# ---------------------------------------------------------------------------
# TestResearchCheckpointEmission
# ---------------------------------------------------------------------------

class TestResearchCheckpointEmission:
    """Verify ResearchInstrument emits checkpoints during iteration loop."""

    def _make_research(self, *, max_iterations=2):
        """Create a ResearchInstrument with mocked tools."""
        from loop_symphony.instruments.research import ResearchInstrument

        claude = MagicMock()
        tavily = MagicMock()

        # Mock Claude responses
        claude.complete = AsyncMock(return_value="problem statement")
        claude.synthesize_with_analysis = AsyncMock(return_value={
            "summary": "Summary",
            "has_contradictions": False,
            "contradiction_hint": None,
        })

        # Mock Tavily search - return empty results
        search_result = MagicMock()
        search_result.answer = "Test answer"
        search_result.results = []
        tavily.search_multiple = AsyncMock(return_value=[search_result])

        inst = ResearchInstrument(claude=claude, tavily=tavily)
        inst.max_iterations = max_iterations
        return inst

    @pytest.mark.asyncio
    async def test_emits_checkpoint_each_iteration(self):
        """Checkpoint is called once per iteration."""
        inst = self._make_research(max_iterations=3)
        checkpoint_fn = AsyncMock()
        ctx = TaskContext(checkpoint_fn=checkpoint_fn)

        await inst.execute("Test query", ctx)

        # Should be called for each iteration (up to max or until termination)
        assert checkpoint_fn.call_count >= 1

    @pytest.mark.asyncio
    async def test_checkpoint_receives_correct_iteration_number(self):
        """First checkpoint has iteration_num=1."""
        inst = self._make_research(max_iterations=1)
        checkpoint_fn = AsyncMock()
        ctx = TaskContext(checkpoint_fn=checkpoint_fn)

        await inst.execute("Test query", ctx)

        call_args = checkpoint_fn.call_args_list[0]
        iteration_num = call_args[0][0]
        assert iteration_num == 1

    @pytest.mark.asyncio
    async def test_checkpoint_output_contains_confidence(self):
        """Checkpoint output_data includes confidence and finding counts."""
        inst = self._make_research(max_iterations=1)
        checkpoint_fn = AsyncMock()
        ctx = TaskContext(checkpoint_fn=checkpoint_fn)

        await inst.execute("Test query", ctx)

        call_args = checkpoint_fn.call_args_list[0]
        output_data = call_args[0][3]  # 4th positional arg
        assert "confidence" in output_data
        assert "total_findings" in output_data
        assert "new_findings" in output_data

    @pytest.mark.asyncio
    async def test_no_error_without_checkpoint_fn(self):
        """Research works normally when checkpoint_fn is None."""
        inst = self._make_research(max_iterations=1)
        ctx = TaskContext()  # no checkpoint_fn

        result = await inst.execute("Test query", ctx)

        assert result.summary == "Summary"

    @pytest.mark.asyncio
    async def test_checkpoint_failure_does_not_kill_research(self):
        """If checkpoint_fn raises, research continues."""
        inst = self._make_research(max_iterations=1)
        checkpoint_fn = AsyncMock(side_effect=RuntimeError("DB down"))
        ctx = TaskContext(checkpoint_fn=checkpoint_fn)

        result = await inst.execute("Test query", ctx)

        # Research should still complete despite checkpoint failure
        assert result.summary == "Summary"
        checkpoint_fn.assert_called_once()


# ---------------------------------------------------------------------------
# TestCheckpointWiring
# ---------------------------------------------------------------------------

class TestCheckpointWiring:
    """Verify execute_task_background wires checkpoint callback."""

    @pytest.mark.asyncio
    async def test_injects_checkpoint_into_context(self):
        """execute_task_background injects checkpoint_fn into request context."""
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.update_task_status = AsyncMock()
        mock_db.complete_task = AsyncMock()
        mock_db.record_iteration = AsyncMock()

        mock_conductor = MagicMock()

        # Capture the request passed to conductor.execute to inspect its context
        captured_request = None

        async def capture_execute(request):
            nonlocal captured_request
            captured_request = request
            # Return a minimal TaskResponse
            from loop_symphony.instruments.base import InstrumentResult
            from loop_symphony.models.finding import Finding, ExecutionMetadata
            from loop_symphony.models.outcome import Outcome
            from loop_symphony.models.task import TaskResponse

            return TaskResponse(
                request_id=request.id,
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

        mock_conductor.execute = capture_execute

        request = TaskRequest(query="Test")
        from loop_symphony.api.events import EventBus
        await routes.execute_task_background(request, mock_conductor, mock_db, EventBus())

        assert captured_request is not None
        assert captured_request.context is not None
        assert captured_request.context.checkpoint_fn is not None

    @pytest.mark.asyncio
    async def test_checkpoint_closure_calls_record_iteration(self):
        """The checkpoint closure calls db.record_iteration with correct task_id."""
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.update_task_status = AsyncMock()
        mock_db.complete_task = AsyncMock()
        mock_db.record_iteration = AsyncMock()

        # When conductor.execute is called, invoke the checkpoint_fn
        async def call_checkpoint(request):
            fn = request.context.checkpoint_fn
            await fn(1, "iteration", {"q": "test"}, {"c": 0.8}, 100)

            from loop_symphony.models.finding import Finding, ExecutionMetadata
            from loop_symphony.models.outcome import Outcome
            from loop_symphony.models.task import TaskResponse

            return TaskResponse(
                request_id=request.id,
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

        mock_conductor = MagicMock()
        mock_conductor.execute = call_checkpoint

        request = TaskRequest(query="Test")
        from loop_symphony.api.events import EventBus
        await routes.execute_task_background(request, mock_conductor, mock_db, EventBus())

        mock_db.record_iteration.assert_called_once_with(
            request.id, 1, "iteration", {"q": "test"}, {"c": 0.8}, 100
        )

    @pytest.mark.asyncio
    async def test_works_without_existing_context(self):
        """execute_task_background works when request.context is None."""
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.update_task_status = AsyncMock()
        mock_db.complete_task = AsyncMock()

        captured_request = None

        async def capture_execute(request):
            nonlocal captured_request
            captured_request = request
            from loop_symphony.models.finding import Finding, ExecutionMetadata
            from loop_symphony.models.outcome import Outcome
            from loop_symphony.models.task import TaskResponse

            return TaskResponse(
                request_id=request.id,
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

        mock_conductor = MagicMock()
        mock_conductor.execute = capture_execute

        request = TaskRequest(query="Test", context=None)
        from loop_symphony.api.events import EventBus
        await routes.execute_task_background(request, mock_conductor, mock_db, EventBus())

        assert captured_request.context is not None
        assert captured_request.context.checkpoint_fn is not None


# ---------------------------------------------------------------------------
# TestCheckpointEndpoint
# ---------------------------------------------------------------------------

class TestCheckpointEndpoint:
    """Verify GET /task/{id}/checkpoints endpoint."""

    @pytest.mark.asyncio
    async def test_returns_iterations(self):
        """Endpoint returns list of iteration records."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value={"id": "t1", "status": "running"})
        mock_db.get_task_iterations = AsyncMock(return_value=[
            {"iteration_num": 1, "phase": "iteration", "duration_ms": 100},
            {"iteration_num": 2, "phase": "iteration", "duration_ms": 200},
        ])
        routes._db_client = mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/t1/checkpoints")

            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert data[0]["iteration_num"] == 1
            assert data[1]["iteration_num"] == 2
        finally:
            routes._db_client = None

    @pytest.mark.asyncio
    async def test_404_for_unknown_task(self):
        """Endpoint returns 404 for unknown task."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value=None)
        routes._db_client = mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/nonexistent/checkpoints")

            assert resp.status_code == 404
        finally:
            routes._db_client = None

    @pytest.mark.asyncio
    async def test_empty_list_for_no_checkpoints(self):
        """Endpoint returns empty list when task has no checkpoints."""
        from httpx import ASGITransport, AsyncClient
        from loop_symphony.main import app
        from loop_symphony.api import routes

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value={"id": "t1", "status": "complete"})
        mock_db.get_task_iterations = AsyncMock(return_value=[])
        routes._db_client = mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/task/t1/checkpoints")

            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            routes._db_client = None
