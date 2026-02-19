"""Tests for nested sub-loop (spawn) functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.exceptions import DepthExceededError
from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext, TaskPreferences, TaskRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(**kwargs):
    """Build a minimal InstrumentResult."""
    defaults = {
        "outcome": Outcome.COMPLETE,
        "findings": [Finding(content="Test", confidence=0.8)],
        "summary": "Test summary",
        "confidence": 0.85,
        "iterations": 1,
    }
    defaults.update(kwargs)
    return InstrumentResult(**defaults)


def _patch_instruments():
    """Context manager to patch all instrument imports."""
    return patch.multiple(
        "loop_symphony.manager.conductor",
        NoteInstrument=MagicMock,
        ResearchInstrument=MagicMock,
        SynthesisInstrument=MagicMock,
        VisionInstrument=MagicMock,
        IngestInstrument=MagicMock,
        DiagnoseInstrument=MagicMock,
        PrescribeInstrument=MagicMock,
        TrackInstrument=MagicMock,
        ReportInstrument=MagicMock,
    )


# ---------------------------------------------------------------------------
# TestDepthExceededError
# ---------------------------------------------------------------------------

class TestDepthExceededError:
    """Verify DepthExceededError exception."""

    def test_stores_depths(self):
        """Exception stores current_depth and max_depth."""
        err = DepthExceededError(4, 3)
        assert err.current_depth == 4
        assert err.max_depth == 3

    def test_message_format(self):
        """Exception message includes both depths."""
        err = DepthExceededError(4, 3)
        assert "4" in str(err)
        assert "3" in str(err)


# ---------------------------------------------------------------------------
# TestTaskContextSpawnFields
# ---------------------------------------------------------------------------

class TestTaskContextSpawnFields:
    """Verify spawn-related fields on TaskContext."""

    def test_depth_defaults_to_zero(self):
        """depth defaults to 0."""
        ctx = TaskContext()
        assert ctx.depth == 0

    def test_max_depth_defaults_to_three(self):
        """max_depth defaults to 3."""
        ctx = TaskContext()
        assert ctx.max_depth == 3

    def test_spawn_fn_defaults_to_none(self):
        """spawn_fn defaults to None."""
        ctx = TaskContext()
        assert ctx.spawn_fn is None

    def test_spawn_fn_excluded_from_serialization(self):
        """spawn_fn is not included in model_dump."""
        fn = AsyncMock()
        ctx = TaskContext(spawn_fn=fn)
        dumped = ctx.model_dump(mode="json")
        assert "spawn_fn" not in dumped

    def test_spawn_fn_preserved_through_model_copy(self):
        """spawn_fn survives model_copy()."""
        fn = AsyncMock()
        ctx = TaskContext(spawn_fn=fn, depth=1)
        copied = ctx.model_copy(update={"input_results": [{}]})
        assert copied.spawn_fn is fn
        assert copied.depth == 1

    def test_depth_and_max_depth_preserved(self):
        """depth and max_depth survive model_copy."""
        ctx = TaskContext(depth=2, max_depth=5)
        copied = ctx.model_copy(update={"user_id": "u1"})
        assert copied.depth == 2
        assert copied.max_depth == 5


# ---------------------------------------------------------------------------
# TestTaskPreferencesMaxDepth
# ---------------------------------------------------------------------------

class TestTaskPreferencesMaxDepth:
    """Verify max_spawn_depth in TaskPreferences."""

    def test_defaults_to_none(self):
        """max_spawn_depth defaults to None."""
        prefs = TaskPreferences()
        assert prefs.max_spawn_depth is None

    def test_accepts_custom_value(self):
        """max_spawn_depth accepts custom value."""
        prefs = TaskPreferences(max_spawn_depth=5)
        assert prefs.max_spawn_depth == 5


# ---------------------------------------------------------------------------
# TestConductorSpawnInjection
# ---------------------------------------------------------------------------

class TestConductorSpawnInjection:
    """Verify Conductor injects spawn_fn into context."""

    @pytest.mark.asyncio
    async def test_injects_spawn_fn(self):
        """execute() injects spawn_fn into context."""
        from loop_symphony.manager.conductor import Conductor

        captured_context = None

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def capture_execute(query, ctx):
                nonlocal captured_context
                captured_context = ctx
                return _make_result()

            inst.execute = capture_execute
            conductor.instruments["note"] = inst

        request = TaskRequest(query="Test")
        await conductor.execute(request)

        assert captured_context is not None
        assert captured_context.spawn_fn is not None
        assert callable(captured_context.spawn_fn)

    @pytest.mark.asyncio
    async def test_injects_depth_and_max_depth(self):
        """execute() injects depth and max_depth into context."""
        from loop_symphony.manager.conductor import Conductor

        captured_context = None

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def capture_execute(query, ctx):
                nonlocal captured_context
                captured_context = ctx
                return _make_result()

            inst.execute = capture_execute
            conductor.instruments["note"] = inst

        request = TaskRequest(query="Test")
        await conductor.execute(request)

        assert captured_context.depth == 0
        assert captured_context.max_depth == 3


# ---------------------------------------------------------------------------
# TestSpawnDepthEnforcement
# ---------------------------------------------------------------------------

class TestSpawnDepthEnforcement:
    """Verify spawn depth is enforced."""

    @pytest.mark.asyncio
    async def test_raises_at_max_depth(self):
        """spawn_fn raises DepthExceededError when at max_depth."""
        from loop_symphony.manager.conductor import Conductor

        spawn_error = None

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def try_spawn(query, ctx):
                nonlocal spawn_error
                if ctx.spawn_fn:
                    try:
                        await ctx.spawn_fn("Sub query")
                    except DepthExceededError as e:
                        spawn_error = e
                return _make_result()

            inst.execute = try_spawn
            conductor.instruments["note"] = inst

        # Start at depth=3 with max_depth=3
        ctx = TaskContext(depth=3, max_depth=3)
        request = TaskRequest(query="Test", context=ctx)
        await conductor.execute(request)

        assert spawn_error is not None
        assert spawn_error.current_depth == 4
        assert spawn_error.max_depth == 3

    @pytest.mark.asyncio
    async def test_preferences_override_max_depth(self):
        """TaskPreferences.max_spawn_depth overrides context max_depth."""
        from loop_symphony.manager.conductor import Conductor

        captured_max_depth = None

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def capture_execute(query, ctx):
                nonlocal captured_max_depth
                captured_max_depth = ctx.max_depth
                return _make_result()

            inst.execute = capture_execute
            conductor.instruments["note"] = inst

        ctx = TaskContext(max_depth=3)
        prefs = TaskPreferences(max_spawn_depth=10)
        request = TaskRequest(query="Test", context=ctx, preferences=prefs)
        await conductor.execute(request)

        assert captured_max_depth == 10


# ---------------------------------------------------------------------------
# TestSpawnResultPropagation
# ---------------------------------------------------------------------------

class TestSpawnResultPropagation:
    """Verify spawn results are properly returned."""

    @pytest.mark.asyncio
    async def test_returns_instrument_result(self):
        """spawn_fn returns InstrumentResult from sub-task."""
        from loop_symphony.manager.conductor import Conductor

        sub_result = None
        call_count = [0]

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def execute_with_spawn(query, ctx):
                nonlocal sub_result
                call_count[0] += 1
                if call_count[0] == 1 and ctx.spawn_fn:
                    sub_result = await ctx.spawn_fn("Sub query")
                    return _make_result()
                else:
                    return _make_result(
                        summary="Sub-task answer",
                        confidence=0.95,
                    )

            inst.execute = execute_with_spawn
            conductor.instruments["note"] = inst

        request = TaskRequest(query="Test")
        await conductor.execute(request)

        assert sub_result is not None
        assert sub_result.summary == "Sub-task answer"
        assert sub_result.confidence == 0.95


# ---------------------------------------------------------------------------
# TestSpawnContextPropagation
# ---------------------------------------------------------------------------

class TestSpawnContextPropagation:
    """Verify context is properly propagated to sub-tasks."""

    @pytest.mark.asyncio
    async def test_checkpoint_fn_propagated(self):
        """checkpoint_fn is available in spawned sub-task."""
        from loop_symphony.manager.conductor import Conductor

        sub_checkpoint_fn = None
        call_count = [0]

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def execute_with_spawn(query, ctx):
                nonlocal sub_checkpoint_fn
                call_count[0] += 1
                if call_count[0] == 1 and ctx.spawn_fn:
                    await ctx.spawn_fn("Sub query")
                    return _make_result()
                else:
                    sub_checkpoint_fn = ctx.checkpoint_fn
                    return _make_result()

            inst.execute = execute_with_spawn
            conductor.instruments["note"] = inst

        checkpoint = AsyncMock()
        ctx = TaskContext(checkpoint_fn=checkpoint)
        request = TaskRequest(query="Test", context=ctx)
        await conductor.execute(request)

        assert sub_checkpoint_fn is checkpoint

    @pytest.mark.asyncio
    async def test_sub_context_merged(self):
        """Sub-context fields are merged into spawned context."""
        from loop_symphony.manager.conductor import Conductor

        sub_input_results = None
        call_count = [0]

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def execute_with_spawn(query, ctx):
                nonlocal sub_input_results
                call_count[0] += 1
                if call_count[0] == 1 and ctx.spawn_fn:
                    sub_ctx = TaskContext(input_results=[{"data": "from_parent"}])
                    await ctx.spawn_fn("Sub query", sub_ctx)
                    return _make_result()
                else:
                    sub_input_results = ctx.input_results
                    return _make_result()

            inst.execute = execute_with_spawn
            conductor.instruments["note"] = inst

        request = TaskRequest(query="Test")
        await conductor.execute(request)

        assert sub_input_results == [{"data": "from_parent"}]

    @pytest.mark.asyncio
    async def test_depth_incremented_in_sub_task(self):
        """Spawned sub-task has incremented depth."""
        from loop_symphony.manager.conductor import Conductor

        sub_depth = None
        call_count = [0]

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def execute_with_spawn(query, ctx):
                nonlocal sub_depth
                call_count[0] += 1
                if call_count[0] == 1 and ctx.spawn_fn:
                    await ctx.spawn_fn("Sub query")
                    return _make_result()
                else:
                    sub_depth = ctx.depth
                    return _make_result()

            inst.execute = execute_with_spawn
            conductor.instruments["note"] = inst

        request = TaskRequest(query="Test")
        await conductor.execute(request)

        assert sub_depth == 1


# ---------------------------------------------------------------------------
# TestNestedExecution
# ---------------------------------------------------------------------------

class TestNestedExecution:
    """Integration-style tests for multi-level nesting."""

    @pytest.mark.asyncio
    async def test_three_level_nesting_succeeds(self):
        """Can nest 3 levels deep with default max_depth=3."""
        from loop_symphony.manager.conductor import Conductor

        max_depth_reached = [0]

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def recursive_execute(query, ctx):
                max_depth_reached[0] = max(max_depth_reached[0], ctx.depth)
                if ctx.spawn_fn and ctx.depth < 3:
                    await ctx.spawn_fn(f"Level {ctx.depth + 1}")
                return _make_result()

            inst.execute = recursive_execute
            conductor.instruments["note"] = inst

        request = TaskRequest(query="Level 0")
        await conductor.execute(request)

        assert max_depth_reached[0] == 3

    @pytest.mark.asyncio
    async def test_four_level_nesting_blocked(self):
        """Fourth level spawn raises DepthExceededError."""
        from loop_symphony.manager.conductor import Conductor

        depth_exceeded = [False]

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def recursive_execute(query, ctx):
                if ctx.spawn_fn:
                    try:
                        await ctx.spawn_fn(f"Level {ctx.depth + 1}")
                    except DepthExceededError:
                        depth_exceeded[0] = True
                return _make_result()

            inst.execute = recursive_execute
            conductor.instruments["note"] = inst

        request = TaskRequest(query="Level 0")
        await conductor.execute(request)

        assert depth_exceeded[0] is True

    @pytest.mark.asyncio
    async def test_custom_max_depth_honored(self):
        """Custom max_spawn_depth in preferences is honored."""
        from loop_symphony.manager.conductor import Conductor

        max_depth_reached = [0]
        depth_exceeded = [False]

        with _patch_instruments():
            conductor = Conductor()
            inst = MagicMock()

            async def recursive_execute(query, ctx):
                max_depth_reached[0] = max(max_depth_reached[0], ctx.depth)
                if ctx.spawn_fn:
                    try:
                        await ctx.spawn_fn(f"Level {ctx.depth + 1}")
                    except DepthExceededError:
                        depth_exceeded[0] = True
                return _make_result()

            inst.execute = recursive_execute
            conductor.instruments["note"] = inst

        # Allow only 1 level of nesting
        prefs = TaskPreferences(max_spawn_depth=1)
        request = TaskRequest(query="Level 0", preferences=prefs)
        await conductor.execute(request)

        assert max_depth_reached[0] == 1
        assert depth_exceeded[0] is True
