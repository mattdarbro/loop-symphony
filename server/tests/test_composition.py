"""Tests for SequentialComposition."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.manager.composition import (
    SequentialComposition,
    _apply_config,
    _build_step_context,
    _restore_config,
    _serialize_result,
)
from loop_symphony.models.finding import Finding
from loop_symphony.models.instrument_config import InstrumentConfig
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext, TaskRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    *,
    outcome=Outcome.COMPLETE,
    confidence=0.85,
    findings=None,
    summary="Test summary",
    iterations=1,
    sources=None,
    discrepancy=None,
    followups=None,
):
    """Build an InstrumentResult for testing."""
    if findings is None:
        findings = [Finding(content="Test finding", source="test", confidence=0.8)]
    return InstrumentResult(
        outcome=outcome,
        findings=findings,
        summary=summary,
        confidence=confidence,
        iterations=iterations,
        sources_consulted=sources or [],
        discrepancy=discrepancy,
        suggested_followups=followups or [],
    )


def _mock_conductor(**instrument_results):
    """Build a mock conductor with named instruments returning given results."""
    conductor = MagicMock()
    instruments = {}
    for name, result in instrument_results.items():
        inst = MagicMock()
        inst.execute = AsyncMock(return_value=result)
        inst.max_iterations = 5
        instruments[name] = inst
    conductor.instruments = instruments
    return conductor


# ---------------------------------------------------------------------------
# TestCompositionConstruction
# ---------------------------------------------------------------------------

class TestCompositionConstruction:
    """Verify SequentialComposition construction."""

    def test_empty_steps_raises(self):
        """Empty steps list raises ValueError."""
        with pytest.raises(ValueError, match="at least one step"):
            SequentialComposition([])

    def test_name_single_step(self):
        """Single step name is just the instrument name."""
        comp = SequentialComposition([("research", None)])
        assert comp.name == "research"

    def test_name_multi_step(self):
        """Multi-step name joins with arrow."""
        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])
        assert comp.name == "research -> synthesis"


# ---------------------------------------------------------------------------
# TestSequentialPipeline
# ---------------------------------------------------------------------------

class TestSequentialPipeline:
    """Verify sequential pipeline execution."""

    @pytest.mark.asyncio
    async def test_two_step_pipeline_runs_both(self):
        """Both instruments are called in a two-step pipeline."""
        research_result = _make_result(sources=["web"])
        synthesis_result = _make_result(summary="Merged", sources=["claude"])

        conductor = _mock_conductor(
            research=research_result,
            synthesis=synthesis_result,
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        result = await comp.execute("Test query", None, conductor)

        conductor.instruments["research"].execute.assert_called_once()
        conductor.instruments["synthesis"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_output_propagation(self):
        """Research output appears in synthesis step's context.input_results."""
        research_result = _make_result(
            findings=[Finding(content="Research finding", source="web", confidence=0.8)],
            sources=["web"],
        )
        synthesis_result = _make_result(summary="Merged")

        conductor = _mock_conductor(
            research=research_result,
            synthesis=synthesis_result,
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        await comp.execute("Test query", None, conductor)

        # Check what context the synthesis step received
        synthesis_call = conductor.instruments["synthesis"].execute.call_args
        step_context = synthesis_call[0][1]  # second positional arg
        assert step_context.input_results is not None
        assert len(step_context.input_results) == 1
        assert step_context.input_results[0]["findings"][0]["content"] == "Research finding"

    @pytest.mark.asyncio
    async def test_returns_last_step_result(self):
        """Composition returns the last step's findings and summary."""
        research_result = _make_result(summary="Research done")
        synthesis_result = _make_result(
            summary="Final merged answer",
            confidence=0.9,
        )

        conductor = _mock_conductor(
            research=research_result,
            synthesis=synthesis_result,
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        result = await comp.execute("Test query", None, conductor)

        assert result.summary == "Final merged answer"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_single_step_works(self):
        """Single-step composition works correctly."""
        note_result = _make_result(summary="Quick answer")
        conductor = _mock_conductor(note=note_result)

        comp = SequentialComposition([("note", None)])
        result = await comp.execute("Simple question", None, conductor)

        assert result.summary == "Quick answer"
        conductor.instruments["note"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_passed_to_all_steps(self):
        """Each step receives the same query string."""
        conductor = _mock_conductor(
            research=_make_result(),
            synthesis=_make_result(),
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        await comp.execute("My specific query", None, conductor)

        for name in ["research", "synthesis"]:
            call_args = conductor.instruments[name].execute.call_args
            assert call_args[0][0] == "My specific query"


# ---------------------------------------------------------------------------
# TestParameterization
# ---------------------------------------------------------------------------

class TestParameterization:
    """Verify InstrumentConfig application and restoration."""

    @pytest.mark.asyncio
    async def test_config_overrides_max_iterations(self):
        """Config sets max_iterations on the instrument during execution."""
        result = _make_result()
        conductor = _mock_conductor(research=result)
        instrument = conductor.instruments["research"]

        assert instrument.max_iterations == 5  # default from _mock_conductor

        comp = SequentialComposition([
            ("research", InstrumentConfig(max_iterations=2)),
        ])

        await comp.execute("Query", None, conductor)

        # After execution, original value should be restored
        assert instrument.max_iterations == 5

    @pytest.mark.asyncio
    async def test_config_restores_on_exception(self):
        """Config is restored even if instrument.execute raises."""
        conductor = _mock_conductor(research=_make_result())
        instrument = conductor.instruments["research"]
        instrument.execute = AsyncMock(side_effect=RuntimeError("Boom"))

        comp = SequentialComposition([
            ("research", InstrumentConfig(max_iterations=2)),
        ])

        with pytest.raises(RuntimeError, match="Boom"):
            await comp.execute("Query", None, conductor)

        assert instrument.max_iterations == 5

    @pytest.mark.asyncio
    async def test_none_config_changes_nothing(self):
        """Step with None config leaves instrument unchanged."""
        conductor = _mock_conductor(research=_make_result())
        instrument = conductor.instruments["research"]

        comp = SequentialComposition([("research", None)])
        await comp.execute("Query", None, conductor)

        assert instrument.max_iterations == 5

    def test_apply_config_with_all_none_fields(self):
        """InstrumentConfig() with all None fields changes nothing."""
        instrument = MagicMock()
        instrument.max_iterations = 10

        originals = _apply_config(instrument, InstrumentConfig())

        assert originals == {}
        assert instrument.max_iterations == 10


# ---------------------------------------------------------------------------
# TestEarlyTermination
# ---------------------------------------------------------------------------

class TestEarlyTermination:
    """Verify early termination behavior."""

    @pytest.mark.asyncio
    async def test_stops_on_inconclusive(self):
        """INCONCLUSIVE in first step prevents second step from running."""
        conductor = _mock_conductor(
            research=_make_result(outcome=Outcome.INCONCLUSIVE),
            synthesis=_make_result(),
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        result = await comp.execute("Query", None, conductor)

        assert result.outcome == Outcome.INCONCLUSIVE
        conductor.instruments["research"].execute.assert_called_once()
        conductor.instruments["synthesis"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_bounded(self):
        """BOUNDED does not cause early termination."""
        conductor = _mock_conductor(
            research=_make_result(outcome=Outcome.BOUNDED),
            synthesis=_make_result(),
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        await comp.execute("Query", None, conductor)

        conductor.instruments["synthesis"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_continues_on_saturated(self):
        """SATURATED does not cause early termination."""
        conductor = _mock_conductor(
            research=_make_result(outcome=Outcome.SATURATED),
            synthesis=_make_result(),
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        await comp.execute("Query", None, conductor)

        conductor.instruments["synthesis"].execute.assert_called_once()


# ---------------------------------------------------------------------------
# TestMetadataAggregation
# ---------------------------------------------------------------------------

class TestMetadataAggregation:
    """Verify metadata aggregation across steps."""

    @pytest.mark.asyncio
    async def test_iterations_summed(self):
        """Total iterations is sum across all steps."""
        conductor = _mock_conductor(
            research=_make_result(iterations=3),
            synthesis=_make_result(iterations=1),
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        result = await comp.execute("Query", None, conductor)

        assert result.iterations == 4

    @pytest.mark.asyncio
    async def test_sources_deduplicated_and_sorted(self):
        """Sources from all steps are deduplicated and sorted."""
        conductor = _mock_conductor(
            research=_make_result(sources=["claude", "web", "tavily"]),
            synthesis=_make_result(sources=["claude"]),
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        result = await comp.execute("Query", None, conductor)

        assert result.sources_consulted == ["claude", "tavily", "web"]

    @pytest.mark.asyncio
    async def test_confidence_from_last_step(self):
        """Confidence comes from the final step, not averaged."""
        conductor = _mock_conductor(
            research=_make_result(confidence=0.7),
            synthesis=_make_result(confidence=0.92),
        )

        comp = SequentialComposition([
            ("research", None),
            ("synthesis", None),
        ])

        result = await comp.execute("Query", None, conductor)

        assert result.confidence == 0.92


# ---------------------------------------------------------------------------
# TestHelpers
# ---------------------------------------------------------------------------

class TestHelpers:
    """Verify private helper functions."""

    def test_serialize_result_has_all_fields(self):
        """Serialized result contains all InstrumentResult fields."""
        result = _make_result(
            summary="Test",
            confidence=0.85,
            iterations=2,
            sources=["src1"],
            discrepancy="A discrepancy",
            followups=["Follow up?"],
        )

        serialized = _serialize_result(result)

        assert serialized["outcome"] == "complete"
        assert serialized["summary"] == "Test"
        assert serialized["confidence"] == 0.85
        assert serialized["iterations"] == 2
        assert serialized["sources_consulted"] == ["src1"]
        assert serialized["discrepancy"] == "A discrepancy"
        assert serialized["suggested_followups"] == ["Follow up?"]
        assert len(serialized["findings"]) == 1

    def test_serialize_findings_to_dicts(self):
        """Finding objects become dicts with content, source, confidence."""
        result = _make_result(
            findings=[
                Finding(content="F1", source="s1", confidence=0.9),
                Finding(content="F2", source="s2", confidence=0.7),
            ]
        )

        serialized = _serialize_result(result)

        assert serialized["findings"][0]["content"] == "F1"
        assert serialized["findings"][0]["source"] == "s1"
        assert serialized["findings"][0]["confidence"] == 0.9
        assert serialized["findings"][1]["content"] == "F2"

    def test_build_step_context_with_base(self):
        """Base context fields are preserved, input_results overridden."""
        base = TaskContext(user_id="user1", conversation_summary="prior")
        step_ctx = _build_step_context(base, [{"findings": []}])

        assert step_ctx.user_id == "user1"
        assert step_ctx.conversation_summary == "prior"
        assert step_ctx.input_results == [{"findings": []}]

    def test_build_step_context_without_base(self):
        """None base creates minimal context with input_results."""
        step_ctx = _build_step_context(None, [{"findings": []}])

        assert step_ctx.input_results == [{"findings": []}]
        assert step_ctx.user_id is None


# ---------------------------------------------------------------------------
# TestConductorExecuteComposition
# ---------------------------------------------------------------------------

class TestConductorExecuteComposition:
    """Verify Conductor.execute_composition() wrapping."""

    @pytest.mark.asyncio
    async def test_wraps_result_in_task_response(self):
        """execute_composition returns a proper TaskResponse."""
        from loop_symphony.manager.conductor import Conductor

        result = _make_result(summary="Composed answer", confidence=0.88)
        mock_comp = MagicMock()
        mock_comp.name = "research -> synthesis"
        mock_comp.execute = AsyncMock(return_value=result)

        with patch("loop_symphony.manager.conductor.NoteInstrument"), \
             patch("loop_symphony.manager.conductor.ResearchInstrument"), \
             patch("loop_symphony.manager.conductor.SynthesisInstrument"), \
             patch("loop_symphony.manager.conductor.VisionInstrument"), \
             patch("loop_symphony.manager.conductor.IngestInstrument"), \
             patch("loop_symphony.manager.conductor.DiagnoseInstrument"), \
             patch("loop_symphony.manager.conductor.PrescribeInstrument"), \
             patch("loop_symphony.manager.conductor.TrackInstrument"), \
             patch("loop_symphony.manager.conductor.ReportInstrument"):
            conductor = Conductor()

        request = TaskRequest(query="Test")
        response = await conductor.execute_composition(mock_comp, request)

        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Composed answer"
        assert response.confidence == 0.88

    @pytest.mark.asyncio
    async def test_metadata_uses_composition_name(self):
        """metadata.instrument_used is the composition name."""
        from loop_symphony.manager.conductor import Conductor

        mock_comp = MagicMock()
        mock_comp.name = "research -> synthesis"
        mock_comp.execute = AsyncMock(return_value=_make_result())

        with patch("loop_symphony.manager.conductor.NoteInstrument"), \
             patch("loop_symphony.manager.conductor.ResearchInstrument"), \
             patch("loop_symphony.manager.conductor.SynthesisInstrument"), \
             patch("loop_symphony.manager.conductor.VisionInstrument"), \
             patch("loop_symphony.manager.conductor.IngestInstrument"), \
             patch("loop_symphony.manager.conductor.DiagnoseInstrument"), \
             patch("loop_symphony.manager.conductor.PrescribeInstrument"), \
             patch("loop_symphony.manager.conductor.TrackInstrument"), \
             patch("loop_symphony.manager.conductor.ReportInstrument"):
            conductor = Conductor()

        request = TaskRequest(query="Test")
        response = await conductor.execute_composition(mock_comp, request)

        assert response.metadata.instrument_used == "research -> synthesis"
        assert response.metadata.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_unknown_instrument_raises(self):
        """Step with unknown instrument name raises ValueError."""
        conductor = _mock_conductor(research=_make_result())
        conductor.instruments = {"research": conductor.instruments["research"]}

        comp = SequentialComposition([
            ("research", None),
            ("nonexistent", None),
        ])

        with pytest.raises(ValueError, match="Unknown instrument 'nonexistent'"):
            await comp.execute("Query", None, conductor)
