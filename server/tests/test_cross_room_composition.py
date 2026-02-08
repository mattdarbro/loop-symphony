"""Tests for cross-room parallel composition (Phase 4C)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.manager.conductor import Conductor
from loop_symphony.manager.cross_room_composition import (
    CrossRoomComposition,
    RoomBranch,
)
from loop_symphony.manager.room_client import RoomClient, RoomDelegationResult
from loop_symphony.manager.room_registry import (
    RoomInfo,
    RoomRegistry,
    RoomRegistration,
)
from loop_symphony.models.finding import ExecutionMetadata, Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskContext, TaskRequest, TaskResponse


def _make_registry_with_rooms() -> RoomRegistry:
    """Create a RoomRegistry with server + local room."""
    registry = RoomRegistry()
    registry.register_server(
        capabilities={"reasoning", "synthesis", "analysis", "web_search"},
        instruments=["note", "research", "synthesis"],
    )
    registry.register(RoomRegistration(
        room_id="local-1",
        room_name="Local Room",
        room_type="local",
        url="http://localhost:8001",
        capabilities=["reasoning"],
        instruments=["local_note"],
    ))
    return registry


def _make_instrument_result(
    summary: str = "Test result",
    confidence: float = 0.8,
    outcome: Outcome = Outcome.COMPLETE,
) -> InstrumentResult:
    return InstrumentResult(
        outcome=outcome,
        findings=[Finding(content=summary, confidence=confidence)],
        summary=summary,
        confidence=confidence,
        iterations=1,
        sources_consulted=["test"],
    )


def _make_task_response(
    summary: str = "Remote result",
    confidence: float = 0.85,
) -> TaskResponse:
    return TaskResponse(
        request_id="test-id",
        outcome=Outcome.COMPLETE,
        findings=[Finding(content=summary, confidence=confidence)],
        summary=summary,
        confidence=confidence,
        metadata=ExecutionMetadata(
            instrument_used="room:local-1/local_note",
            iterations=1,
            duration_ms=100,
            process_type=ProcessType.SEMI_AUTONOMIC,
            room_id="local-1",
        ),
    )


class TestRoomBranch:
    """Tests for RoomBranch dataclass."""

    def test_basic_branch(self):
        branch = RoomBranch(query="What is Python?")
        assert branch.query == "What is Python?"
        assert branch.room_id is None
        assert branch.instrument is None
        assert branch.prefer_local is False

    def test_branch_with_room_hint(self):
        branch = RoomBranch(
            query="Analyze my health data",
            room_id="local-1",
            prefer_local=True,
        )
        assert branch.room_id == "local-1"
        assert branch.prefer_local is True

    def test_branch_with_capabilities(self):
        branch = RoomBranch(
            query="Search the web",
            required_capabilities={"web_search"},
        )
        assert "web_search" in branch.required_capabilities


class TestCrossRoomCompositionConstruction:
    """Tests for CrossRoomComposition construction."""

    def test_requires_branches(self):
        with pytest.raises(ValueError, match="requires at least one branch"):
            CrossRoomComposition(branches=[])

    def test_name_property(self):
        comp = CrossRoomComposition(branches=[
            RoomBranch(query="Query A", room_id="local-1"),
            RoomBranch(query="Query B"),
        ])
        assert "local-1" in comp.name
        assert "auto" in comp.name
        assert "synthesis" in comp.name

    def test_default_merge_instrument(self):
        comp = CrossRoomComposition(branches=[RoomBranch(query="Q")])
        assert comp.merge_instrument == "synthesis"


class TestCrossRoomExecution:
    """Tests for cross-room execution logic."""

    @pytest.mark.asyncio
    async def test_all_server_branches_execute_locally(self):
        """When all branches route to server, execute via conductor's instruments."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        # Mock instruments
        mock_note = AsyncMock()
        mock_note.execute = AsyncMock(return_value=_make_instrument_result("Note result"))
        mock_note.required_capabilities = frozenset({"reasoning"})

        mock_synthesis = AsyncMock()
        mock_synthesis.execute = AsyncMock(
            return_value=_make_instrument_result("Merged result", confidence=0.9)
        )
        conductor.instruments["note"] = mock_note
        conductor.instruments["synthesis"] = mock_synthesis

        comp = CrossRoomComposition(branches=[
            RoomBranch(query="Public question A"),
            RoomBranch(query="Public question B"),
        ])

        result = await comp.execute("Combine A and B", None, conductor)

        # Merge instrument should be called since we have 2 branches
        assert result.outcome == Outcome.COMPLETE
        assert mock_synthesis.execute.called

    @pytest.mark.asyncio
    async def test_single_branch_no_merge(self):
        """Single successful branch returns directly (no merge step)."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        mock_note = AsyncMock()
        mock_note.execute = AsyncMock(
            return_value=_make_instrument_result("Single result")
        )
        mock_note.required_capabilities = frozenset({"reasoning"})
        conductor.instruments["note"] = mock_note

        comp = CrossRoomComposition(branches=[
            RoomBranch(query="Just one question"),
        ])

        result = await comp.execute("One question", None, conductor)

        assert result.summary == "Single result"

    @pytest.mark.asyncio
    async def test_mixed_room_branches(self):
        """Branches can go to different rooms."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        # Mock server instrument
        mock_note = AsyncMock()
        mock_note.execute = AsyncMock(
            return_value=_make_instrument_result("Server result")
        )
        mock_note.required_capabilities = frozenset({"reasoning"})
        conductor.instruments["note"] = mock_note

        # Mock synthesis for merge
        mock_synthesis = AsyncMock()
        mock_synthesis.execute = AsyncMock(
            return_value=_make_instrument_result("Merged", confidence=0.88)
        )
        conductor.instruments["synthesis"] = mock_synthesis

        # Mock room delegation for local branch
        mock_delegation = RoomDelegationResult(
            success=True,
            response=_make_task_response("Local result"),
            room_id="local-1",
            latency_ms=100,
        )

        with patch.object(
            RoomClient, "delegate", new_callable=AsyncMock, return_value=mock_delegation
        ):
            comp = CrossRoomComposition(branches=[
                RoomBranch(query="Private health data", room_id="local-1", prefer_local=True),
                RoomBranch(query="Public question"),
            ])

            result = await comp.execute("Combine results", None, conductor)

        assert result.outcome == Outcome.COMPLETE

    @pytest.mark.asyncio
    async def test_remote_branch_failure_falls_back(self):
        """Failed remote branch falls back to server execution."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        mock_note = AsyncMock()
        mock_note.execute = AsyncMock(
            return_value=_make_instrument_result("Fallback result")
        )
        mock_note.required_capabilities = frozenset({"reasoning"})
        conductor.instruments["note"] = mock_note

        # Mock room delegation failure
        mock_delegation = RoomDelegationResult(
            success=False,
            error="Connection refused",
            room_id="local-1",
            latency_ms=50,
        )

        with patch.object(
            RoomClient, "delegate", new_callable=AsyncMock, return_value=mock_delegation
        ):
            comp = CrossRoomComposition(branches=[
                RoomBranch(query="Private query", room_id="local-1"),
            ])

            result = await comp.execute("Query", None, conductor)

        # Should have fallen back to server
        assert result.outcome == Outcome.COMPLETE
        assert result.summary == "Fallback result"

    @pytest.mark.asyncio
    async def test_all_branches_fail_returns_inconclusive(self):
        """When all branches fail, return INCONCLUSIVE."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        # Make server instrument raise
        mock_note = AsyncMock()
        mock_note.execute = AsyncMock(side_effect=RuntimeError("Instrument crashed"))
        mock_note.required_capabilities = frozenset({"reasoning"})
        conductor.instruments["note"] = mock_note

        comp = CrossRoomComposition(branches=[
            RoomBranch(query="Query 1", instrument="note"),
            RoomBranch(query="Query 2", instrument="note"),
        ])

        result = await comp.execute("Failing", None, conductor)

        assert result.outcome == Outcome.INCONCLUSIVE
        assert result.confidence == 0.0
        assert "failed" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_partial_failure_merges_successful(self):
        """Successful branches merged even when some fail."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        # First instrument succeeds, second fails
        call_count = 0

        async def varying_execute(query, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_instrument_result("Good result")
            raise RuntimeError("Branch 2 failed")

        mock_note = AsyncMock()
        mock_note.execute = AsyncMock(side_effect=varying_execute)
        mock_note.required_capabilities = frozenset({"reasoning"})
        conductor.instruments["note"] = mock_note

        mock_synthesis = AsyncMock()
        mock_synthesis.execute = AsyncMock(
            return_value=_make_instrument_result("Partial merge")
        )
        conductor.instruments["synthesis"] = mock_synthesis

        comp = CrossRoomComposition(branches=[
            RoomBranch(query="Q1", instrument="note"),
            RoomBranch(query="Q2", instrument="note"),
        ])

        result = await comp.execute("Merge", None, conductor)

        # Single success → returned directly (no merge needed since only 1 succeeded
        # and there were failures)
        # Actually: 1 successful + failures = merge still happens? Let me check...
        # Looking at the code: if len(successful) == 1 and not failed → return directly
        # Here: len(successful) == 1 and failed is truthy → merge is called
        assert result.outcome == Outcome.COMPLETE
        assert result.discrepancy is not None  # Should include failure note


class TestCrossRoomMetadata:
    """Tests for metadata tracking across rooms."""

    @pytest.mark.asyncio
    async def test_conductor_execute_cross_room(self):
        """Test the Conductor.execute_cross_room() convenience method."""
        registry = _make_registry_with_rooms()
        conductor = Conductor(room_registry=registry)

        mock_note = AsyncMock()
        mock_note.execute = AsyncMock(
            return_value=_make_instrument_result("Result")
        )
        mock_note.required_capabilities = frozenset({"reasoning"})
        conductor.instruments["note"] = mock_note

        request = TaskRequest(query="Test cross-room")
        branches = [RoomBranch(query="Sub-query", instrument="note")]

        response = await conductor.execute_cross_room(branches, request)

        assert response.outcome == Outcome.COMPLETE
        assert response.metadata.process_type == ProcessType.CONSCIOUS

    @pytest.mark.asyncio
    async def test_serialization_for_merge(self):
        """Verify _serialize_result produces correct dict format."""
        result = _make_instrument_result("Test", confidence=0.85)
        serialized = CrossRoomComposition._serialize_result(result)

        assert serialized["outcome"] == "complete"
        assert serialized["confidence"] == 0.85
        assert serialized["summary"] == "Test"
        assert isinstance(serialized["findings"], list)
