"""Tests for task manager / semi-autonomic layer (Phase 3F)."""

import asyncio
import pytest
from datetime import datetime, UTC

from loop_symphony.manager.task_manager import (
    ManagedTask,
    TaskManager,
    TaskState,
)


class TestTaskStateEnum:
    """Tests for TaskState enum."""

    def test_states(self):
        assert TaskState.QUEUED.value == "queued"
        assert TaskState.RUNNING.value == "running"
        assert TaskState.CANCELLING.value == "cancelling"
        assert TaskState.CANCELLED.value == "cancelled"
        assert TaskState.COMPLETED.value == "completed"
        assert TaskState.FAILED.value == "failed"


class TestManagedTaskModel:
    """Tests for ManagedTask dataclass."""

    def test_basic_task(self):
        task = ManagedTask(
            task_id="test-123",
            query="What is 2+2?",
            instrument="note",
        )
        assert task.task_id == "test-123"
        assert task.query == "What is 2+2?"
        assert task.instrument == "note"
        assert task.state == TaskState.QUEUED

    def test_to_dict(self):
        task = ManagedTask(
            task_id="test-123",
            query="Test query",
            instrument="research",
            state=TaskState.RUNNING,
        )
        d = task.to_dict()

        assert d["task_id"] == "test-123"
        assert d["instrument"] == "research"
        assert d["state"] == "running"
        assert "created_at" in d

    def test_long_query_truncated(self):
        long_query = "x" * 200
        task = ManagedTask(task_id="t1", query=long_query)
        d = task.to_dict()

        assert len(d["query"]) == 103  # 100 chars + "..."
        assert d["query"].endswith("...")

    def test_running_seconds(self):
        task = ManagedTask(task_id="t1", query="test")
        task.started_at = datetime.now(UTC)

        d = task.to_dict()
        assert d["running_seconds"] is not None
        assert d["running_seconds"] >= 0


class TestTaskManagerBasics:
    """Tests for TaskManager basic operations."""

    @pytest.mark.asyncio
    async def test_register_task(self):
        manager = TaskManager()
        managed = await manager.register_task(
            task_id="test-1",
            query="Test query",
            instrument="note",
        )

        assert managed.task_id == "test-1"
        assert managed.state == TaskState.QUEUED

    @pytest.mark.asyncio
    async def test_start_task(self):
        manager = TaskManager()
        await manager.register_task("test-1", "Query")

        # Create a dummy asyncio task
        async def dummy():
            await asyncio.sleep(10)

        asyncio_task = asyncio.create_task(dummy())
        try:
            await manager.start_task("test-1", asyncio_task)

            task = manager.get_task("test-1")
            assert task.state == TaskState.RUNNING
            assert task.started_at is not None
        finally:
            asyncio_task.cancel()
            try:
                await asyncio_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_update_progress(self):
        manager = TaskManager()
        await manager.register_task("test-1", "Query")
        await manager.update_progress("test-1", 3, "Processing...")

        task = manager.get_task("test-1")
        assert task.current_iteration == 3
        assert task.progress == "Processing..."

    @pytest.mark.asyncio
    async def test_complete_task(self):
        manager = TaskManager()
        await manager.register_task("test-1", "Query")
        await manager.complete_task("test-1")

        task = manager.get_task("test-1")
        assert task.state == TaskState.COMPLETED

    @pytest.mark.asyncio
    async def test_fail_task(self):
        manager = TaskManager()
        await manager.register_task("test-1", "Query")
        await manager.fail_task("test-1", "Something went wrong")

        task = manager.get_task("test-1")
        assert task.state == TaskState.FAILED
        assert "Something went wrong" in task.progress


class TestTaskManagerCancellation:
    """Tests for task cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_running_task(self):
        manager = TaskManager()
        await manager.register_task("test-1", "Query")

        # Create a real task that can be cancelled
        async def cancellable():
            await asyncio.sleep(10)

        asyncio_task = asyncio.create_task(cancellable())
        await manager.start_task("test-1", asyncio_task)

        # Cancel it
        result = await manager.cancel_task("test-1")
        assert result is True

        task = manager.get_task("test-1")
        assert task.state == TaskState.CANCELLING

        # Wait for cancellation to complete
        with pytest.raises(asyncio.CancelledError):
            await asyncio_task

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self):
        manager = TaskManager()
        result = await manager.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self):
        manager = TaskManager()
        await manager.register_task("test-1", "Query")
        await manager.complete_task("test-1")

        result = await manager.cancel_task("test-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_cancelled(self):
        manager = TaskManager()
        await manager.register_task("test-1", "Query")
        await manager.mark_cancelled("test-1")

        task = manager.get_task("test-1")
        assert task.state == TaskState.CANCELLED


class TestTaskManagerQueries:
    """Tests for querying tasks."""

    @pytest.mark.asyncio
    async def test_get_active_tasks(self):
        manager = TaskManager()

        # Create tasks in different states
        await manager.register_task("queued-1", "Q1")  # QUEUED
        await manager.register_task("running-1", "R1")

        # Simulate running state
        manager._tasks["running-1"].state = TaskState.RUNNING

        await manager.register_task("completed-1", "C1")
        await manager.complete_task("completed-1")  # COMPLETED

        active = manager.get_active_tasks()
        active_ids = [t.task_id for t in active]

        assert "queued-1" in active_ids
        assert "running-1" in active_ids
        assert "completed-1" not in active_ids

    @pytest.mark.asyncio
    async def test_get_active_tasks_filtered(self):
        manager = TaskManager()

        await manager.register_task("t1", "Q", app_id="app-1")
        await manager.register_task("t2", "Q", app_id="app-2")
        await manager.register_task("t3", "Q", app_id="app-1", user_id="user-1")

        # Filter by app
        app1_tasks = manager.get_active_tasks(app_id="app-1")
        assert len(app1_tasks) == 2

        # Filter by user
        user_tasks = manager.get_active_tasks(app_id="app-1", user_id="user-1")
        assert len(user_tasks) == 1

    @pytest.mark.asyncio
    async def test_get_all_tasks(self):
        manager = TaskManager()

        for i in range(5):
            await manager.register_task(f"t{i}", f"Query {i}")

        all_tasks = manager.get_all_tasks(limit=3)
        assert len(all_tasks) == 3

    def test_active_count(self):
        manager = TaskManager()
        assert manager.active_count == 0
        assert manager.total_count == 0

    @pytest.mark.asyncio
    async def test_counts(self):
        manager = TaskManager()

        await manager.register_task("t1", "Q")
        await manager.register_task("t2", "Q")
        await manager.complete_task("t2")

        assert manager.active_count == 1
        assert manager.total_count == 2


class TestTaskManagerCleanup:
    """Tests for task cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_old_tasks(self):
        manager = TaskManager()

        # Create and complete a task
        await manager.register_task("old-1", "Q")
        await manager.complete_task("old-1")

        # Manually set old timestamp
        manager._tasks["old-1"].created_at = datetime(2020, 1, 1, tzinfo=UTC)

        cleaned = await manager.cleanup_old_tasks(max_age_seconds=1)
        assert cleaned == 1
        assert manager.get_task("old-1") is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_running_tasks(self):
        manager = TaskManager()

        await manager.register_task("running-1", "Q")
        manager._tasks["running-1"].state = TaskState.RUNNING
        manager._tasks["running-1"].created_at = datetime(2020, 1, 1, tzinfo=UTC)

        cleaned = await manager.cleanup_old_tasks(max_age_seconds=1)
        assert cleaned == 0
        assert manager.get_task("running-1") is not None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent_tasks(self):
        manager = TaskManager()

        await manager.register_task("recent-1", "Q")
        await manager.complete_task("recent-1")
        # Don't change timestamp - it's recent

        cleaned = await manager.cleanup_old_tasks(max_age_seconds=3600)
        assert cleaned == 0
