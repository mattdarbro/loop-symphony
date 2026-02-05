"""Tests for ParallelComposition."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.manager.composition import ParallelComposition
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome


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
# TestParallelConstruction
# ---------------------------------------------------------------------------

class TestParallelConstruction:
    """Verify ParallelComposition construction."""

    def test_empty_branches_raises(self):
        """Empty branches list raises ValueError."""
        with pytest.raises(ValueError, match="at least one branch"):
            ParallelComposition([])

    def test_name_format(self):
        """Name format includes parallel() and merge instrument."""
        comp = ParallelComposition(["research", "note"])
        assert comp.name == "parallel(research | note) -> synthesis"

    @pytest.mark.asyncio
    async def test_unknown_branch_raises(self):
        """Unknown branch instrument raises ValueError on execute."""
        conductor = _mock_conductor(
            research=_make_result(),
            synthesis=_make_result(),
        )

        comp = ParallelComposition(["research", "nonexistent"])

        with pytest.raises(ValueError, match="Unknown instrument 'nonexistent'"):
            await comp.execute("Query", None, conductor)


# ---------------------------------------------------------------------------
# TestParallelExecution
# ---------------------------------------------------------------------------

class TestParallelExecution:
    """Verify parallel execution behavior."""

    @pytest.mark.asyncio
    async def test_two_branches_both_execute(self):
        """Both branch instruments are called."""
        conductor = _mock_conductor(
            research=_make_result(sources=["web"]),
            note=_make_result(sources=["claude"]),
            synthesis=_make_result(summary="Merged"),
        )

        comp = ParallelComposition(["research", "note"])
        await comp.execute("Query", None, conductor)

        conductor.instruments["research"].execute.assert_called_once()
        conductor.instruments["note"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_results_passed_to_merge_as_input_results(self):
        """Successful branch results are serialized as input_results for merge."""
        conductor = _mock_conductor(
            research=_make_result(
                findings=[Finding(content="Research finding", source="web", confidence=0.9)],
            ),
            note=_make_result(
                findings=[Finding(content="Note finding", source="claude", confidence=0.8)],
            ),
            synthesis=_make_result(summary="Merged"),
        )

        comp = ParallelComposition(["research", "note"])
        await comp.execute("Query", None, conductor)

        # Check what the synthesis instrument received
        merge_call = conductor.instruments["synthesis"].execute.call_args
        merge_context = merge_call[0][1]  # second positional arg
        assert merge_context.input_results is not None
        assert len(merge_context.input_results) == 2

    @pytest.mark.asyncio
    async def test_returns_merged_result(self):
        """Returns the merge instrument's result."""
        conductor = _mock_conductor(
            research=_make_result(),
            note=_make_result(),
            synthesis=_make_result(summary="Final merged", confidence=0.92),
        )

        comp = ParallelComposition(["research", "note"])
        result = await comp.execute("Query", None, conductor)

        assert result.summary == "Final merged"
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_query_passed_to_all_branches(self):
        """Each branch receives the same query."""
        conductor = _mock_conductor(
            research=_make_result(),
            note=_make_result(),
            synthesis=_make_result(),
        )

        comp = ParallelComposition(["research", "note"])
        await comp.execute("My query", None, conductor)

        for name in ["research", "note"]:
            call_args = conductor.instruments[name].execute.call_args
            assert call_args[0][0] == "My query"

    @pytest.mark.asyncio
    async def test_single_branch_works(self):
        """Single branch composition works correctly."""
        conductor = _mock_conductor(
            research=_make_result(summary="Single branch"),
            synthesis=_make_result(summary="Merged single"),
        )

        comp = ParallelComposition(["research"])
        result = await comp.execute("Query", None, conductor)

        conductor.instruments["research"].execute.assert_called_once()
        conductor.instruments["synthesis"].execute.assert_called_once()
        assert result.summary == "Merged single"


# ---------------------------------------------------------------------------
# TestParallelTimeout
# ---------------------------------------------------------------------------

class TestParallelTimeout:
    """Verify timeout behavior."""

    @pytest.mark.asyncio
    async def test_slow_branch_times_out_fast_succeeds(self):
        """Slow branch times out, fast branch succeeds, synthesis gets partial."""
        fast_result = _make_result(summary="Fast result")
        merge_result = _make_result(summary="Merged partial")

        conductor = MagicMock()
        fast_inst = MagicMock()
        fast_inst.execute = AsyncMock(return_value=fast_result)

        slow_inst = MagicMock()

        async def slow_execute(query, context):
            await asyncio.sleep(10)
            return _make_result()

        slow_inst.execute = slow_execute

        merge_inst = MagicMock()
        merge_inst.execute = AsyncMock(return_value=merge_result)

        conductor.instruments = {
            "fast": fast_inst,
            "slow": slow_inst,
            "synthesis": merge_inst,
        }

        comp = ParallelComposition(["fast", "slow"], timeout_seconds=0.01)
        result = await comp.execute("Query", None, conductor)

        assert result.summary == "Merged partial"
        # Discrepancy should mention the failed branch
        assert result.discrepancy is not None
        assert "slow" in result.discrepancy

    @pytest.mark.asyncio
    async def test_all_branches_timeout_returns_inconclusive(self):
        """All branches timing out returns INCONCLUSIVE."""
        conductor = MagicMock()

        async def slow_execute(query, context):
            await asyncio.sleep(10)
            return _make_result()

        slow1 = MagicMock()
        slow1.execute = slow_execute
        slow2 = MagicMock()
        slow2.execute = slow_execute

        conductor.instruments = {
            "slow1": slow1,
            "slow2": slow2,
            "synthesis": MagicMock(),
        }

        comp = ParallelComposition(["slow1", "slow2"], timeout_seconds=0.01)
        result = await comp.execute("Query", None, conductor)

        assert result.outcome == Outcome.INCONCLUSIVE
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_no_timeout_runs_without_limit(self):
        """Without timeout, branches run to completion."""
        conductor = _mock_conductor(
            research=_make_result(),
            synthesis=_make_result(),
        )

        comp = ParallelComposition(["research"], timeout_seconds=None)
        result = await comp.execute("Query", None, conductor)

        conductor.instruments["research"].execute.assert_called_once()


# ---------------------------------------------------------------------------
# TestPartialFailure
# ---------------------------------------------------------------------------

class TestPartialFailure:
    """Verify partial failure handling."""

    @pytest.mark.asyncio
    async def test_one_fails_others_succeed(self):
        """One branch raises, others succeed, synthesis merges successful."""
        conductor = MagicMock()

        good_inst = MagicMock()
        good_inst.execute = AsyncMock(return_value=_make_result(summary="Good"))

        bad_inst = MagicMock()
        bad_inst.execute = AsyncMock(side_effect=RuntimeError("Boom"))

        merge_inst = MagicMock()
        merge_inst.execute = AsyncMock(return_value=_make_result(summary="Merged"))

        conductor.instruments = {
            "good": good_inst,
            "bad": bad_inst,
            "synthesis": merge_inst,
        }

        comp = ParallelComposition(["good", "bad"])
        result = await comp.execute("Query", None, conductor)

        assert result.summary == "Merged"
        merge_inst.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_branch_noted_in_discrepancy(self):
        """Failed branch info appears in discrepancy."""
        conductor = MagicMock()

        good_inst = MagicMock()
        good_inst.execute = AsyncMock(return_value=_make_result())

        bad_inst = MagicMock()
        bad_inst.execute = AsyncMock(side_effect=RuntimeError("Connection lost"))

        merge_inst = MagicMock()
        merge_inst.execute = AsyncMock(return_value=_make_result())

        conductor.instruments = {
            "good": good_inst,
            "bad": bad_inst,
            "synthesis": merge_inst,
        }

        comp = ParallelComposition(["good", "bad"])
        result = await comp.execute("Query", None, conductor)

        assert result.discrepancy is not None
        assert "bad" in result.discrepancy
        assert "Connection lost" in result.discrepancy

    @pytest.mark.asyncio
    async def test_all_fail_returns_inconclusive(self):
        """All branches failing returns INCONCLUSIVE with failure details."""
        conductor = MagicMock()

        bad1 = MagicMock()
        bad1.execute = AsyncMock(side_effect=RuntimeError("Error 1"))
        bad2 = MagicMock()
        bad2.execute = AsyncMock(side_effect=RuntimeError("Error 2"))

        conductor.instruments = {
            "bad1": bad1,
            "bad2": bad2,
            "synthesis": MagicMock(),
        }

        comp = ParallelComposition(["bad1", "bad2"])
        result = await comp.execute("Query", None, conductor)

        assert result.outcome == Outcome.INCONCLUSIVE
        assert result.confidence == 0.0
        assert "bad1" in result.discrepancy
        assert "bad2" in result.discrepancy


# ---------------------------------------------------------------------------
# TestParallelMetadata
# ---------------------------------------------------------------------------

class TestParallelMetadata:
    """Verify metadata aggregation across branches."""

    @pytest.mark.asyncio
    async def test_iterations_summed(self):
        """Total iterations is sum across branches plus merge."""
        conductor = _mock_conductor(
            research=_make_result(iterations=3),
            note=_make_result(iterations=1),
            synthesis=_make_result(iterations=2),
        )

        comp = ParallelComposition(["research", "note"])
        result = await comp.execute("Query", None, conductor)

        assert result.iterations == 6  # 3 + 1 + 2

    @pytest.mark.asyncio
    async def test_sources_deduplicated_and_sorted(self):
        """Sources from all branches and merge are deduplicated and sorted."""
        conductor = _mock_conductor(
            research=_make_result(sources=["web", "tavily"]),
            note=_make_result(sources=["claude", "web"]),
            synthesis=_make_result(sources=["claude"]),
        )

        comp = ParallelComposition(["research", "note"])
        result = await comp.execute("Query", None, conductor)

        assert result.sources_consulted == ["claude", "tavily", "web"]

    @pytest.mark.asyncio
    async def test_confidence_from_merge_step(self):
        """Confidence comes from the merge step, not branches."""
        conductor = _mock_conductor(
            research=_make_result(confidence=0.7),
            note=_make_result(confidence=0.6),
            synthesis=_make_result(confidence=0.95),
        )

        comp = ParallelComposition(["research", "note"])
        result = await comp.execute("Query", None, conductor)

        assert result.confidence == 0.95
