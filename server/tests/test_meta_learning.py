"""Tests for meta-learning / saved arrangements (Phase 3C)."""

import pytest
from uuid import uuid4

from loop_symphony.manager.arrangement_tracker import (
    ArrangementTracker,
    MIN_EXECUTIONS_FOR_SUGGESTION,
    MIN_SUCCESS_RATE_FOR_SUGGESTION,
    MIN_CONFIDENCE_FOR_SUGGESTION,
)
from loop_symphony.manager.conductor import Conductor
from loop_symphony.models.arrangement import ArrangementProposal, ArrangementStep
from loop_symphony.models.loop_proposal import LoopPhase, LoopProposal
from loop_symphony.models.saved_arrangement import (
    ArrangementExecution,
    ArrangementStats,
    ArrangementSuggestion,
    SaveArrangementRequest,
    SavedArrangement,
)


class TestArrangementExecutionModel:
    """Tests for ArrangementExecution model."""

    def test_basic_execution(self):
        execution = ArrangementExecution(
            arrangement_id="abc123",
            task_id="task-1",
            outcome="complete",
            confidence=0.9,
            duration_ms=5000,
        )
        assert execution.arrangement_id == "abc123"
        assert execution.outcome == "complete"


class TestArrangementStatsModel:
    """Tests for ArrangementStats model."""

    def test_empty_stats(self):
        stats = ArrangementStats()
        assert stats.total_executions == 0
        assert stats.success_rate == 0.0

    def test_success_rate_calculation(self):
        stats = ArrangementStats(
            total_executions=10,
            successful_executions=8,
        )
        assert stats.success_rate == 0.8

    def test_stats_with_values(self):
        stats = ArrangementStats(
            total_executions=5,
            successful_executions=4,
            average_confidence=0.85,
            average_duration_ms=3000,
        )
        assert stats.success_rate == 0.8
        assert stats.average_confidence == 0.85


class TestSavedArrangementModel:
    """Tests for SavedArrangement model."""

    def test_composition_arrangement(self):
        proposal = ArrangementProposal(
            type="sequential",
            rationale="Research then synthesize",
            termination_criteria="Done",
            steps=[
                ArrangementStep(instrument="research"),
                ArrangementStep(instrument="synthesis"),
            ],
        )

        saved = SavedArrangement(
            id=uuid4(),
            name="research_synthesis",
            description="Research then synthesize",
            arrangement_type="composition",
            composition_spec=proposal,
        )

        assert saved.arrangement_type == "composition"
        assert saved.composition_spec is not None
        assert saved.loop_spec is None

    def test_loop_arrangement(self):
        proposal = LoopProposal(
            name="fact_check",
            description="Verify claims",
            phases=[
                LoopPhase(name="extract", description="Extract"),
                LoopPhase(name="verify", description="Verify"),
            ],
            termination_criteria="Done",
        )

        saved = SavedArrangement(
            id=uuid4(),
            name="fact_check",
            description="Verify claims",
            arrangement_type="loop",
            loop_spec=proposal,
        )

        assert saved.arrangement_type == "loop"
        assert saved.loop_spec is not None


class TestArrangementTrackerRecording:
    """Tests for ArrangementTracker execution recording."""

    def test_record_execution(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        tracker.record_execution(
            arrangement=proposal,
            task_id="task-1",
            outcome="complete",
            confidence=0.9,
            duration_ms=1000,
        )

        stats = tracker.get_stats(proposal)
        assert stats.total_executions == 1
        assert stats.successful_executions == 1

    def test_multiple_executions(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="sequential",
            rationale="Test",
            termination_criteria="Done",
            steps=[
                ArrangementStep(instrument="research"),
                ArrangementStep(instrument="synthesis"),
            ],
        )

        # Record 5 executions
        for i in range(5):
            tracker.record_execution(
                arrangement=proposal,
                task_id=f"task-{i}",
                outcome="complete" if i < 4 else "bounded",
                confidence=0.8 + (i * 0.02),
                duration_ms=1000 + (i * 100),
            )

        stats = tracker.get_stats(proposal)
        assert stats.total_executions == 5
        assert stats.successful_executions == 4
        assert stats.success_rate == 0.8


class TestArrangementTrackerSuggestions:
    """Tests for ArrangementTracker suggestion logic."""

    def test_no_suggestion_for_few_executions(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        # Record only 2 executions (below threshold)
        for i in range(2):
            tracker.record_execution(
                arrangement=proposal,
                task_id=f"task-{i}",
                outcome="complete",
                confidence=0.9,
                duration_ms=1000,
            )

        assert not tracker.should_suggest_saving(proposal)
        assert tracker.get_suggestion(proposal) is None

    def test_no_suggestion_for_low_success_rate(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        # Record 5 executions with low success rate
        for i in range(5):
            tracker.record_execution(
                arrangement=proposal,
                task_id=f"task-{i}",
                outcome="complete" if i < 2 else "inconclusive",
                confidence=0.5,
                duration_ms=1000,
            )

        assert not tracker.should_suggest_saving(proposal)

    def test_suggestion_for_high_performer(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="sequential",
            rationale="Good research pipeline",
            termination_criteria="High confidence",
            steps=[
                ArrangementStep(instrument="research"),
                ArrangementStep(instrument="synthesis"),
            ],
        )

        # Record enough successful executions
        for i in range(5):
            tracker.record_execution(
                arrangement=proposal,
                task_id=f"task-{i}",
                outcome="complete",
                confidence=0.85,
                duration_ms=2000,
            )

        assert tracker.should_suggest_saving(proposal)
        suggestion = tracker.get_suggestion(proposal)
        assert suggestion is not None
        assert suggestion.success_rate == 1.0
        assert suggestion.confidence == 0.85


class TestArrangementTrackerSaving:
    """Tests for ArrangementTracker saving logic."""

    def test_save_arrangement(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        request = SaveArrangementRequest(
            name="quick_note",
            description="Quick note-taking",
            composition_spec=proposal,
        )

        saved = tracker.save_arrangement(request)
        assert saved.name == "quick_note"
        assert saved.arrangement_type == "composition"

    def test_save_loop_arrangement(self):
        tracker = ArrangementTracker()
        proposal = LoopProposal(
            name="fact_check",
            description="Verify claims",
            phases=[
                LoopPhase(name="extract", description="Extract"),
                LoopPhase(name="verify", description="Verify"),
            ],
            termination_criteria="Done",
        )

        request = SaveArrangementRequest(
            name="fact_checker",
            description="Verify factual claims",
            loop_spec=proposal,
        )

        saved = tracker.save_arrangement(request)
        assert saved.name == "fact_checker"
        assert saved.arrangement_type == "loop"

    def test_reject_duplicate_name(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        request = SaveArrangementRequest(
            name="my_arrangement",
            description="Test",
            composition_spec=proposal,
        )

        tracker.save_arrangement(request)

        with pytest.raises(ValueError, match="already exists"):
            tracker.save_arrangement(request)

    def test_reject_empty_spec(self):
        tracker = ArrangementTracker()

        request = SaveArrangementRequest(
            name="empty",
            description="No spec provided",
        )

        with pytest.raises(ValueError, match="composition_spec or loop_spec"):
            tracker.save_arrangement(request)


class TestArrangementTrackerRetrieval:
    """Tests for ArrangementTracker retrieval methods."""

    def test_get_saved_arrangements(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        # Save two arrangements
        for i in range(2):
            request = SaveArrangementRequest(
                name=f"arrangement_{i}",
                description=f"Test {i}",
                composition_spec=proposal,
            )
            tracker.save_arrangement(request)

        arrangements = tracker.get_saved_arrangements()
        assert len(arrangements) == 2

    def test_get_saved_arrangement_by_id(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        request = SaveArrangementRequest(
            name="test",
            description="Test",
            composition_spec=proposal,
        )

        saved = tracker.save_arrangement(request)
        retrieved = tracker.get_saved_arrangement(str(saved.id))

        assert retrieved is not None
        assert retrieved.name == "test"

    def test_get_saved_arrangement_by_name(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        request = SaveArrangementRequest(
            name="my_arrangement",
            description="Test",
            composition_spec=proposal,
        )

        tracker.save_arrangement(request)
        retrieved = tracker.get_saved_arrangement_by_name("my_arrangement")

        assert retrieved is not None
        assert retrieved.name == "my_arrangement"

    def test_delete_arrangement(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        request = SaveArrangementRequest(
            name="to_delete",
            description="Test",
            composition_spec=proposal,
        )

        saved = tracker.save_arrangement(request)
        assert tracker.delete_arrangement(str(saved.id))
        assert tracker.get_saved_arrangement(str(saved.id)) is None


class TestArrangementTrackerMatching:
    """Tests for ArrangementTracker query matching."""

    def test_find_matching_arrangement(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="research",
        )

        request = SaveArrangementRequest(
            name="research_ai",
            description="Research AI topics",
            composition_spec=proposal,
            query_patterns=["AI research", "artificial intelligence"],
        )

        tracker.save_arrangement(request)

        match = tracker.find_matching_arrangement("I need AI research on neural networks")
        assert match is not None
        assert match.name == "research_ai"

    def test_no_match_for_unrelated_query(self):
        tracker = ArrangementTracker()
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="research",
        )

        request = SaveArrangementRequest(
            name="research_ai",
            description="Research AI topics",
            composition_spec=proposal,
            query_patterns=["AI research"],
        )

        tracker.save_arrangement(request)

        match = tracker.find_matching_arrangement("What's the weather today?")
        assert match is None


class TestConductorTrackerIntegration:
    """Tests for Conductor tracker integration."""

    def test_conductor_has_tracker(self):
        conductor = Conductor()
        assert conductor.tracker is not None

    def test_tracker_is_same_instance(self):
        conductor = Conductor()
        tracker1 = conductor.tracker
        tracker2 = conductor.tracker
        assert tracker1 is tracker2


class TestSaveArrangementRequest:
    """Tests for SaveArrangementRequest model."""

    def test_model_allows_empty_specs(self):
        # Model itself allows creation without specs
        # Validation happens in ArrangementTracker.save_arrangement()
        request = SaveArrangementRequest(
            name="test",
            description="Test",
        )
        assert request.composition_spec is None
        assert request.loop_spec is None

    def test_with_composition_spec(self):
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        request = SaveArrangementRequest(
            name="test",
            description="Test",
            composition_spec=proposal,
        )

        assert request.composition_spec is not None
        assert request.loop_spec is None

    def test_with_query_patterns(self):
        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        request = SaveArrangementRequest(
            name="test",
            description="Test",
            composition_spec=proposal,
            query_patterns=["pattern1", "pattern2"],
            tags=["tag1"],
        )

        assert len(request.query_patterns) == 2
        assert len(request.tags) == 1
