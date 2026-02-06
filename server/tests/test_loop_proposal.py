"""Tests for loop proposal system (Phase 3B)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import json

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.manager.conductor import Conductor
from loop_symphony.manager.loop_executor import LoopExecutor
from loop_symphony.manager.loop_proposer import (
    LoopProposer,
    KNOWN_INSTRUMENTS,
    SCIENTIFIC_METHOD_PHASES,
)
from loop_symphony.models.loop_proposal import (
    LoopExecutionPlan,
    LoopPhase,
    LoopProposal,
    LoopProposalValidation,
)
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext, TaskRequest


class TestLoopPhaseModel:
    """Tests for LoopPhase model."""

    def test_instrument_action(self):
        phase = LoopPhase(
            name="research",
            description="Research the topic",
            action="instrument",
            instrument="research",
        )
        assert phase.action == "instrument"
        assert phase.instrument == "research"

    def test_prompt_action(self):
        phase = LoopPhase(
            name="analyze",
            description="Analyze findings",
            action="prompt",
            prompt_template="Analyze: {query}",
        )
        assert phase.action == "prompt"
        assert "{query}" in phase.prompt_template

    def test_spawn_action(self):
        phase = LoopPhase(
            name="deep_dive",
            description="Deep dive into topic",
            action="spawn",
        )
        assert phase.action == "spawn"

    def test_default_max_iterations(self):
        phase = LoopPhase(name="test", description="Test")
        assert phase.max_iterations == 1


class TestLoopProposalModel:
    """Tests for LoopProposal model."""

    def test_basic_proposal(self):
        proposal = LoopProposal(
            name="fact_check",
            description="Verify factual claims",
            phases=[
                LoopPhase(name="extract", description="Extract claims"),
                LoopPhase(name="verify", description="Verify claims"),
            ],
            termination_criteria="All claims verified",
        )
        assert proposal.name == "fact_check"
        assert len(proposal.phases) == 2

    def test_min_phases_validation(self):
        with pytest.raises(ValueError):
            LoopProposal(
                name="invalid",
                description="Only one phase",
                phases=[LoopPhase(name="only", description="Only one")],
                termination_criteria="Done",
            )

    def test_max_iterations_bounds(self):
        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(name="a", description="A"),
                LoopPhase(name="b", description="B"),
            ],
            termination_criteria="Done",
            max_total_iterations=15,
        )
        assert proposal.max_total_iterations == 15

    def test_default_capabilities(self):
        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(name="a", description="A"),
                LoopPhase(name="b", description="B"),
            ],
            termination_criteria="Done",
        )
        assert "reasoning" in proposal.required_capabilities


class TestLoopProposalValidation:
    """Tests for LoopProposalValidation model."""

    def test_valid_result(self):
        validation = LoopProposalValidation(valid=True)
        assert validation.valid
        assert validation.errors == []

    def test_invalid_with_errors(self):
        validation = LoopProposalValidation(
            valid=False,
            errors=["Missing scientific method phase"],
        )
        assert not validation.valid
        assert len(validation.errors) == 1

    def test_coverage_dict(self):
        validation = LoopProposalValidation(
            valid=True,
            scientific_method_coverage={
                "hypothesize": True,
                "gather": True,
                "analyze": False,
                "synthesize": True,
            },
        )
        assert validation.scientific_method_coverage["hypothesize"]
        assert not validation.scientific_method_coverage["analyze"]


class TestLoopProposerParsing:
    """Tests for LoopProposer response parsing."""

    def test_parses_valid_response(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        response = json.dumps({
            "name": "fact_check",
            "description": "Verify claims",
            "phases": [
                {"name": "extract", "description": "Extract claims", "action": "prompt", "prompt_template": "Extract: {query}"},
                {"name": "verify", "description": "Verify", "action": "instrument", "instrument": "research"},
            ],
            "termination_criteria": "All verified",
            "max_total_iterations": 10,
            "required_capabilities": ["reasoning", "web_search"],
            "scientific_method_phases": ["hypothesize", "gather", "analyze", "synthesize"],
        })

        proposal = proposer._parse_response(response)
        assert proposal.name == "fact_check"
        assert len(proposal.phases) == 2

    def test_handles_markdown_code_blocks(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        response = """```json
{
    "name": "test",
    "description": "Test",
    "phases": [
        {"name": "a", "description": "A"},
        {"name": "b", "description": "B"}
    ],
    "termination_criteria": "Done"
}
```"""

        proposal = proposer._parse_response(response)
        assert proposal.name == "test"

    def test_falls_back_on_parse_error(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        response = "This is not JSON"

        proposal = proposer._parse_response(response)
        assert proposal.name == "fallback_research"
        assert len(proposal.phases) == 2


class TestLoopProposerValidation:
    """Tests for LoopProposer.validate()."""

    def test_validates_good_proposal(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        proposal = LoopProposal(
            name="research_loop",
            description="Research and synthesize",
            phases=[
                LoopPhase(
                    name="hypothesize",
                    description="Form hypothesis about the topic",
                    action="prompt",
                    prompt_template="Hypothesize about: {query}",
                ),
                LoopPhase(
                    name="gather",
                    description="Gather information",
                    action="instrument",
                    instrument="research",
                ),
                LoopPhase(
                    name="analyze",
                    description="Analyze findings",
                    action="prompt",
                    prompt_template="Analyze: {previous_findings}",
                ),
                LoopPhase(
                    name="synthesize",
                    description="Draw conclusions",
                    action="instrument",
                    instrument="synthesis",
                ),
            ],
            termination_criteria="High confidence synthesis achieved",
            scientific_method_phases=["hypothesize", "gather", "analyze", "synthesize"],
        )

        validation = proposer.validate(proposal)
        assert validation.valid

    def test_rejects_unknown_instrument(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(
                    name="bad",
                    description="Bad phase",
                    action="instrument",
                    instrument="unknown_instrument",
                ),
                LoopPhase(name="ok", description="OK"),
            ],
            termination_criteria="Done",
        )

        validation = proposer.validate(proposal)
        assert not validation.valid
        assert any("unknown_instrument" in e for e in validation.errors)

    def test_rejects_missing_prompt_template(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(
                    name="bad",
                    description="Prompt action but no template",
                    action="prompt",
                    # Missing prompt_template
                ),
                LoopPhase(name="ok", description="OK"),
            ],
            termination_criteria="Done",
        )

        validation = proposer.validate(proposal)
        assert not validation.valid
        assert any("prompt_template" in e for e in validation.errors)

    def test_warns_on_partial_scientific_coverage(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        proposal = LoopProposal(
            name="partial",
            description="Partial coverage",
            phases=[
                LoopPhase(
                    name="gather",
                    description="Gather data",
                    action="instrument",
                    instrument="research",
                ),
                LoopPhase(
                    name="synthesize",
                    description="Synthesize",
                    action="instrument",
                    instrument="synthesis",
                ),
            ],
            termination_criteria="Done with synthesis",
            scientific_method_phases=["gather", "synthesize"],
        )

        validation = proposer.validate(proposal)
        assert validation.valid  # Still valid, just warnings
        assert len(validation.warnings) > 0

    def test_rejects_insufficient_coverage(self):
        claude = MagicMock()
        proposer = LoopProposer(claude=claude)

        proposal = LoopProposal(
            name="minimal",
            description="Too minimal",
            phases=[
                LoopPhase(name="step1", description="Do something"),
                LoopPhase(name="step2", description="Do something else"),
            ],
            termination_criteria="Done",
            scientific_method_phases=[],  # No coverage declared
        )

        validation = proposer.validate(proposal)
        assert not validation.valid
        assert any("scientific method" in e.lower() for e in validation.errors)


class TestLoopProposerPlan:
    """Tests for LoopProposer.propose()."""

    @pytest.mark.asyncio
    async def test_calls_claude(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value=json.dumps({
            "name": "test",
            "description": "Test",
            "phases": [
                {"name": "a", "description": "A"},
                {"name": "b", "description": "B"},
            ],
            "termination_criteria": "Done",
        }))
        proposer = LoopProposer(claude=claude)

        proposal = await proposer.propose("Test query")

        claude.complete.assert_called_once()
        assert "Test query" in claude.complete.call_args.kwargs["prompt"]


class TestLoopExecutor:
    """Tests for LoopExecutor."""

    @pytest.mark.asyncio
    async def test_executes_instrument_phase(self):
        claude = MagicMock()
        conductor = Conductor()

        # Mock the research instrument
        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[],
            summary="Research done",
            confidence=0.8,
            iterations=2,
            sources_consulted=["web"],
        )
        conductor.instruments["research"].execute = AsyncMock(return_value=mock_result)

        executor = LoopExecutor(claude=claude, conductor=conductor)

        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(
                    name="research",
                    description="Research",
                    action="instrument",
                    instrument="research",
                ),
                LoopPhase(
                    name="synthesize",
                    description="Synthesize",
                    action="instrument",
                    instrument="synthesis",
                ),
            ],
            termination_criteria="Done",
        )

        # Also mock synthesis
        conductor.instruments["synthesis"].execute = AsyncMock(return_value=mock_result)

        result = await executor.execute(proposal, "Test query")

        assert result.outcome in [Outcome.COMPLETE, Outcome.SATURATED, Outcome.BOUNDED]

    @pytest.mark.asyncio
    async def test_executes_prompt_phase(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value="Analysis complete")
        conductor = Conductor()

        executor = LoopExecutor(claude=claude, conductor=conductor)

        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(
                    name="analyze",
                    description="Analyze",
                    action="prompt",
                    prompt_template="Analyze this: {query}",
                ),
                LoopPhase(
                    name="conclude",
                    description="Conclude",
                    action="prompt",
                    prompt_template="Conclude based on: {previous_findings}",
                ),
            ],
            termination_criteria="Done",
        )

        result = await executor.execute(proposal, "Test query")

        assert len(result.findings) == 2  # One per prompt phase
        assert claude.complete.call_count == 2


class TestConductorLoopMethods:
    """Tests for Conductor loop proposal methods."""

    def test_get_loop_proposer_creates_proposer(self):
        conductor = Conductor()
        proposer = conductor._get_loop_proposer()
        assert proposer is not None

    def test_get_loop_proposer_returns_same_instance(self):
        conductor = Conductor()
        proposer1 = conductor._get_loop_proposer()
        proposer2 = conductor._get_loop_proposer()
        assert proposer1 is proposer2

    def test_get_loop_executor_creates_executor(self):
        conductor = Conductor()
        executor = conductor._get_loop_executor()
        assert executor is not None

    @pytest.mark.asyncio
    async def test_propose_loop(self):
        conductor = Conductor()
        mock_proposer = MagicMock()
        mock_proposer.propose = AsyncMock(return_value=LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(name="a", description="A"),
                LoopPhase(name="b", description="B"),
            ],
            termination_criteria="Done",
        ))
        conductor._loop_proposer = mock_proposer

        proposal = await conductor.propose_loop("Test query")

        assert proposal.name == "test"
        mock_proposer.propose.assert_called_once_with("Test query")

    def test_validate_loop_proposal(self):
        conductor = Conductor()

        proposal = LoopProposal(
            name="research_analyze",
            description="Research and analyze",
            phases=[
                LoopPhase(
                    name="hypothesize",
                    description="Form hypothesis",
                    action="prompt",
                    prompt_template="Hypothesize: {query}",
                ),
                LoopPhase(
                    name="gather",
                    description="Gather info",
                    action="instrument",
                    instrument="research",
                ),
                LoopPhase(
                    name="analyze",
                    description="Analyze",
                    action="prompt",
                    prompt_template="Analyze: {previous_findings}",
                ),
                LoopPhase(
                    name="synthesize",
                    description="Synthesize",
                    action="instrument",
                    instrument="synthesis",
                ),
            ],
            termination_criteria="High confidence achieved",
            scientific_method_phases=["hypothesize", "gather", "analyze", "synthesize"],
        )

        validation = conductor.validate_loop_proposal(proposal)
        assert validation.valid

    def test_get_loop_execution_plan(self):
        conductor = Conductor()

        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(name="a", description="A", max_iterations=2),
                LoopPhase(name="b", description="B", max_iterations=3),
            ],
            termination_criteria="Done",
            max_total_iterations=10,
        )

        plan = conductor.get_loop_execution_plan(proposal)

        assert isinstance(plan, LoopExecutionPlan)
        assert plan.proposal == proposal
        assert plan.estimated_iterations <= 10
        assert plan.requires_approval

    @pytest.mark.asyncio
    async def test_execute_loop_proposal(self):
        conductor = Conductor()

        # Mock the executor
        mock_executor = MagicMock()
        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[],
            summary="Done",
            confidence=0.9,
            iterations=3,
            sources_consulted=[],
        )
        mock_executor.execute = AsyncMock(return_value=mock_result)
        conductor._loop_executor = mock_executor

        proposal = LoopProposal(
            name="test",
            description="Test",
            phases=[
                LoopPhase(
                    name="gather",
                    description="Gather",
                    action="instrument",
                    instrument="research",
                ),
                LoopPhase(
                    name="synthesize",
                    description="Synthesize",
                    action="instrument",
                    instrument="synthesis",
                ),
            ],
            termination_criteria="Done",
            scientific_method_phases=["gather", "synthesize"],
        )

        request = TaskRequest(query="Test")
        response = await conductor.execute_loop_proposal(proposal, request)

        assert response.outcome == Outcome.COMPLETE
        assert "loop:test" in response.metadata.instrument_used
