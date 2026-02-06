"""Tests for novel arrangement generation (Phase 3A)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import json

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.manager.arrangement_planner import (
    ArrangementPlanner,
    INSTRUMENT_CATALOG,
    PLANNING_PROMPT,
)
from loop_symphony.manager.conductor import Conductor
from loop_symphony.models.arrangement import (
    ArrangementProposal,
    ArrangementStep,
    ArrangementValidation,
)
from loop_symphony.models.instrument_config import InstrumentConfig
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskRequest


class TestArrangementProposalModel:
    """Tests for ArrangementProposal model."""

    def test_single_type(self):
        proposal = ArrangementProposal(
            type="single",
            rationale="Simple query",
            termination_criteria="Single pass",
            instrument="note",
        )
        assert proposal.type == "single"
        assert proposal.instrument == "note"

    def test_sequential_type(self):
        proposal = ArrangementProposal(
            type="sequential",
            rationale="Multi-step research",
            termination_criteria="High confidence",
            steps=[
                ArrangementStep(instrument="research"),
                ArrangementStep(instrument="synthesis"),
            ],
        )
        assert proposal.type == "sequential"
        assert len(proposal.steps) == 2

    def test_parallel_type(self):
        proposal = ArrangementProposal(
            type="parallel",
            rationale="Multiple perspectives",
            termination_criteria="Consensus reached",
            branches=["research", "note"],
            merge_instrument="synthesis",
        )
        assert proposal.type == "parallel"
        assert len(proposal.branches) == 2

    def test_step_with_config(self):
        step = ArrangementStep(
            instrument="research",
            config=InstrumentConfig(max_iterations=3),
        )
        assert step.config.max_iterations == 3


class TestArrangementValidation:
    """Tests for ArrangementValidation model."""

    def test_valid_result(self):
        validation = ArrangementValidation(valid=True)
        assert validation.valid
        assert validation.errors == []

    def test_invalid_with_errors(self):
        validation = ArrangementValidation(
            valid=False,
            errors=["Unknown instrument: foo"],
        )
        assert not validation.valid
        assert len(validation.errors) == 1

    def test_valid_with_warnings(self):
        validation = ArrangementValidation(
            valid=True,
            warnings=["No termination criteria"],
        )
        assert validation.valid
        assert len(validation.warnings) == 1


class TestInstrumentCatalog:
    """Tests for the instrument catalog."""

    def test_has_all_instruments(self):
        assert "note" in INSTRUMENT_CATALOG
        assert "research" in INSTRUMENT_CATALOG
        assert "synthesis" in INSTRUMENT_CATALOG
        assert "vision" in INSTRUMENT_CATALOG

    def test_instrument_has_required_fields(self):
        for name, info in INSTRUMENT_CATALOG.items():
            assert "description" in info
            assert "capabilities" in info
            assert "max_iterations" in info
            assert "best_for" in info


class TestArrangementPlannerParsing:
    """Tests for ArrangementPlanner response parsing."""

    def test_parses_single_response(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        response = json.dumps({
            "type": "single",
            "rationale": "Simple question",
            "termination_criteria": "One pass",
            "instrument": "note",
        })

        proposal = planner._parse_response(response)
        assert proposal.type == "single"
        assert proposal.instrument == "note"

    def test_parses_sequential_response(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        response = json.dumps({
            "type": "sequential",
            "rationale": "Research then synthesize",
            "termination_criteria": "Synthesis complete",
            "steps": [
                {"instrument": "research", "config": None},
                {"instrument": "synthesis", "config": None},
            ],
        })

        proposal = planner._parse_response(response)
        assert proposal.type == "sequential"
        assert len(proposal.steps) == 2
        assert proposal.steps[0].instrument == "research"

    def test_parses_parallel_response(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        response = json.dumps({
            "type": "parallel",
            "rationale": "Multiple perspectives",
            "termination_criteria": "Merge complete",
            "branches": ["research", "note"],
            "merge_instrument": "synthesis",
            "timeout_seconds": 30.0,
        })

        proposal = planner._parse_response(response)
        assert proposal.type == "parallel"
        assert proposal.branches == ["research", "note"]
        assert proposal.timeout_seconds == 30.0

    def test_handles_markdown_code_blocks(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        response = """```json
{
    "type": "single",
    "rationale": "Simple",
    "termination_criteria": "Done",
    "instrument": "note"
}
```"""

        proposal = planner._parse_response(response)
        assert proposal.type == "single"
        assert proposal.instrument == "note"

    def test_falls_back_on_parse_error(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        response = "This is not JSON"

        proposal = planner._parse_response(response)
        assert proposal.type == "single"
        assert proposal.instrument == "note"
        assert "Fallback" in proposal.rationale


class TestArrangementPlannerValidation:
    """Tests for ArrangementPlanner.validate()."""

    def test_validates_single_with_known_instrument(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        validation = planner.validate(proposal)
        assert validation.valid

    def test_rejects_single_with_unknown_instrument(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="unknown_instrument",
        )

        validation = planner.validate(proposal)
        assert not validation.valid
        assert any("unknown_instrument" in e for e in validation.errors)

    def test_validates_sequential_with_known_instruments(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="sequential",
            rationale="Test",
            termination_criteria="Done",
            steps=[
                ArrangementStep(instrument="research"),
                ArrangementStep(instrument="synthesis"),
            ],
        )

        validation = planner.validate(proposal)
        assert validation.valid

    def test_rejects_sequential_with_unknown_step(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="sequential",
            rationale="Test",
            termination_criteria="Done",
            steps=[
                ArrangementStep(instrument="research"),
                ArrangementStep(instrument="bad_instrument"),
            ],
        )

        validation = planner.validate(proposal)
        assert not validation.valid
        assert any("bad_instrument" in e for e in validation.errors)

    def test_validates_parallel_with_known_branches(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="parallel",
            rationale="Test",
            termination_criteria="Done",
            branches=["research", "note"],
            merge_instrument="synthesis",
        )

        validation = planner.validate(proposal)
        assert validation.valid

    def test_rejects_parallel_with_unknown_branch(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="parallel",
            rationale="Test",
            termination_criteria="Done",
            branches=["research", "bad_branch"],
            merge_instrument="synthesis",
        )

        validation = planner.validate(proposal)
        assert not validation.valid
        assert any("bad_branch" in e for e in validation.errors)

    def test_rejects_parallel_with_unknown_merge(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="parallel",
            rationale="Test",
            termination_criteria="Done",
            branches=["research", "note"],
            merge_instrument="bad_merge",
        )

        validation = planner.validate(proposal)
        assert not validation.valid
        assert any("bad_merge" in e for e in validation.errors)

    def test_warns_on_missing_termination_criteria(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="",
            instrument="note",
        )

        validation = planner.validate(proposal)
        assert validation.valid  # Still valid, just a warning
        assert len(validation.warnings) > 0


class TestArrangementPlannerPlan:
    """Tests for ArrangementPlanner.plan()."""

    @pytest.mark.asyncio
    async def test_calls_claude_with_prompt(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value=json.dumps({
            "type": "single",
            "rationale": "Simple",
            "termination_criteria": "Done",
            "instrument": "note",
        }))
        planner = ArrangementPlanner(claude=claude)

        proposal = await planner.plan("What is 2+2?")

        claude.complete.assert_called_once()
        call_args = claude.complete.call_args
        assert "What is 2+2?" in call_args.kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_returns_proposal(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value=json.dumps({
            "type": "sequential",
            "rationale": "Research then synthesize",
            "termination_criteria": "High confidence",
            "steps": [
                {"instrument": "research", "config": None},
                {"instrument": "synthesis", "config": None},
            ],
        }))
        planner = ArrangementPlanner(claude=claude)

        proposal = await planner.plan("Research AI trends")

        assert proposal.type == "sequential"
        assert len(proposal.steps) == 2


class TestConductorArrangementMethods:
    """Tests for Conductor arrangement methods."""

    def test_get_planner_creates_planner(self):
        conductor = Conductor()
        planner = conductor._get_planner()
        assert planner is not None

    def test_get_planner_returns_same_instance(self):
        conductor = Conductor()
        planner1 = conductor._get_planner()
        planner2 = conductor._get_planner()
        assert planner1 is planner2

    @pytest.mark.asyncio
    async def test_plan_arrangement(self):
        conductor = Conductor()
        # Mock the planner
        mock_planner = MagicMock()
        mock_planner.plan = AsyncMock(return_value=ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        ))
        conductor._planner = mock_planner

        proposal = await conductor.plan_arrangement("Test query")

        assert proposal.type == "single"
        mock_planner.plan.assert_called_once_with("Test query")

    def test_validate_arrangement(self):
        conductor = Conductor()

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )

        validation = conductor.validate_arrangement(proposal)
        assert validation.valid

    @pytest.mark.asyncio
    async def test_execute_arrangement_single(self):
        conductor = Conductor()
        # Mock the note instrument with a real InstrumentResult
        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[],
            summary="Test result",
            confidence=0.9,
            iterations=1,
            sources_consulted=[],
        )

        conductor.instruments["note"].execute = AsyncMock(return_value=mock_result)

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="note",
        )
        request = TaskRequest(query="Test")

        response = await conductor.execute_arrangement(proposal, request)

        assert "novel:note" in response.metadata.instrument_used

    @pytest.mark.asyncio
    async def test_execute_arrangement_invalid_raises(self):
        conductor = Conductor()

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="bad_instrument",
        )
        request = TaskRequest(query="Test")

        with pytest.raises(ValueError, match="Invalid arrangement"):
            await conductor.execute_arrangement(proposal, request)


class TestConductorExecuteNovel:
    """Tests for Conductor.execute_novel()."""

    @pytest.mark.asyncio
    async def test_plans_and_executes(self):
        conductor = Conductor()

        # Mock the planner
        mock_planner = MagicMock()
        mock_planner.plan = AsyncMock(return_value=ArrangementProposal(
            type="single",
            rationale="Simple query",
            termination_criteria="One pass",
            instrument="note",
        ))
        mock_planner.validate = MagicMock(return_value=ArrangementValidation(valid=True))
        conductor._planner = mock_planner

        # Mock the instrument with a real InstrumentResult
        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[],
            summary="Test",
            confidence=0.9,
            iterations=1,
            sources_consulted=[],
        )
        conductor.instruments["note"].execute = AsyncMock(return_value=mock_result)

        request = TaskRequest(query="What is 2+2?")
        response = await conductor.execute_novel(request)

        assert response is not None
        mock_planner.plan.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_on_invalid_proposal(self):
        conductor = Conductor()

        # Mock the planner to return invalid proposal
        mock_planner = MagicMock()
        mock_planner.plan = AsyncMock(return_value=ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="bad_instrument",
        ))
        mock_planner.validate = MagicMock(return_value=ArrangementValidation(
            valid=False,
            errors=["Unknown instrument"],
        ))
        conductor._planner = mock_planner

        # Mock standard execute
        mock_response = MagicMock()
        conductor.execute = AsyncMock(return_value=mock_response)

        request = TaskRequest(query="Test")
        response = await conductor.execute_novel(request)

        # Should fall back to standard execution
        conductor.execute.assert_called_once()
