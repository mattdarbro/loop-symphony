"""Tests for SynthesisInstrument."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.instruments.synthesis import SynthesisInstrument, _RESYNTHESIS_THRESHOLD
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input_result(
    *,
    summary="Summary",
    confidence=0.8,
    findings=None,
    outcome="complete",
    sources=None,
    discrepancy=None,
):
    """Build a serialized InstrumentResult dict for testing."""
    if findings is None:
        findings = [{"content": "Finding content", "source": "test", "confidence": 0.8}]
    return {
        "outcome": outcome,
        "findings": findings,
        "summary": summary,
        "confidence": confidence,
        "iterations": 1,
        "sources_consulted": sources or ["test_source"],
        "discrepancy": discrepancy,
        "suggested_followups": [],
    }


def _no_contradiction_synthesis():
    """Return a synthesis result with no contradictions."""
    return {
        "summary": "Synthesized summary",
        "has_contradictions": False,
        "contradiction_hint": None,
    }


def _contradiction_synthesis(hint="Sources disagree"):
    """Return a synthesis result with contradictions."""
    return {
        "summary": "Synthesized summary with contradictions",
        "has_contradictions": True,
        "contradiction_hint": hint,
    }


def _discrepancy_analysis(severity="moderate"):
    """Return a discrepancy analysis result."""
    return {
        "description": "Test discrepancy",
        "severity": severity,
        "conflicting_claims": ["Claim A", "Claim B"],
        "suggested_refinements": ["Refine query 1", "Refine query 2"],
    }


@pytest.fixture
def instrument():
    """Create a SynthesisInstrument with mocked Claude client."""
    with patch("loop_symphony.instruments.synthesis.ClaudeClient"):
        inst = SynthesisInstrument()
        inst.claude = MagicMock()
        inst.claude.synthesize_with_analysis = AsyncMock(
            return_value=_no_contradiction_synthesis()
        )
        inst.claude.analyze_discrepancy = AsyncMock(
            return_value=_discrepancy_analysis()
        )
        yield inst


# ---------------------------------------------------------------------------
# TestSynthesisProtocol
# ---------------------------------------------------------------------------

class TestSynthesisProtocol:
    """Verify SynthesisInstrument class attributes and construction."""

    def test_required_capabilities(self):
        """SynthesisInstrument requires reasoning and synthesis."""
        assert SynthesisInstrument.required_capabilities == frozenset(
            {"reasoning", "synthesis"}
        )

    def test_max_iterations(self):
        """SynthesisInstrument has max_iterations of 2."""
        assert SynthesisInstrument.max_iterations == 2

    def test_name(self):
        """SynthesisInstrument is named 'synthesis'."""
        assert SynthesisInstrument.name == "synthesis"

    def test_is_base_instrument(self):
        """SynthesisInstrument is a BaseInstrument subclass."""
        with patch("loop_symphony.instruments.synthesis.ClaudeClient"):
            inst = SynthesisInstrument()
        assert isinstance(inst, BaseInstrument)

    def test_accepts_injected_claude(self):
        """SynthesisInstrument accepts an injected claude client."""
        mock_claude = MagicMock()
        inst = SynthesisInstrument(claude=mock_claude)
        assert inst.claude is mock_claude

    def test_zero_arg_construction(self):
        """SynthesisInstrument can be created with no args."""
        with patch("loop_symphony.instruments.synthesis.ClaudeClient"):
            inst = SynthesisInstrument()
            assert inst.claude is not None


# ---------------------------------------------------------------------------
# TestSynthesisBasic
# ---------------------------------------------------------------------------

class TestSynthesisBasic:
    """Verify basic synthesis execution."""

    @pytest.mark.asyncio
    async def test_merges_multiple_results(self, instrument):
        """Synthesis merges findings from multiple input results."""
        context = TaskContext(
            input_results=[
                _make_input_result(
                    findings=[{"content": "Finding A", "source": "src_a", "confidence": 0.8}],
                    sources=["src_a"],
                ),
                _make_input_result(
                    findings=[{"content": "Finding B", "source": "src_b", "confidence": 0.9}],
                    sources=["src_b"],
                ),
            ]
        )

        result = await instrument.execute("Test query", context)

        assert result.outcome == Outcome.COMPLETE
        assert len(result.findings) == 2
        instrument.claude.synthesize_with_analysis.assert_called_once()

    @pytest.mark.asyncio
    async def test_preserves_all_findings(self, instrument):
        """All findings from all inputs appear in the output."""
        context = TaskContext(
            input_results=[
                _make_input_result(
                    findings=[
                        {"content": "F1", "source": "a", "confidence": 0.8},
                        {"content": "F2", "source": "a", "confidence": 0.7},
                    ]
                ),
                _make_input_result(
                    findings=[{"content": "F3", "source": "b", "confidence": 0.9}]
                ),
            ]
        )

        result = await instrument.execute("Test query", context)

        contents = [f.content for f in result.findings]
        assert "F1" in contents
        assert "F2" in contents
        assert "F3" in contents

    @pytest.mark.asyncio
    async def test_deduplicates_sources(self, instrument):
        """Sources from multiple inputs are deduplicated."""
        context = TaskContext(
            input_results=[
                _make_input_result(sources=["claude", "tavily"]),
                _make_input_result(sources=["claude", "wikipedia"]),
            ]
        )

        result = await instrument.execute("Test query", context)

        assert result.sources_consulted == ["claude", "tavily", "wikipedia"]

    @pytest.mark.asyncio
    async def test_single_iteration_on_high_confidence(self, instrument):
        """High confidence input results produce only 1 iteration."""
        context = TaskContext(
            input_results=[
                _make_input_result(confidence=0.9),
                _make_input_result(confidence=0.85),
            ]
        )

        result = await instrument.execute("Test query", context)

        assert result.iterations == 1


# ---------------------------------------------------------------------------
# TestSynthesisEmptyInput
# ---------------------------------------------------------------------------

class TestSynthesisEmptyInput:
    """Verify graceful handling of missing/empty input."""

    @pytest.mark.asyncio
    async def test_no_context_returns_bounded(self, instrument):
        """context=None returns Outcome.BOUNDED with confidence 0.0."""
        result = await instrument.execute("Test query", None)

        assert result.outcome == Outcome.BOUNDED
        assert result.confidence == 0.0
        assert result.iterations == 0

    @pytest.mark.asyncio
    async def test_no_input_results_returns_bounded(self, instrument):
        """input_results=None returns Outcome.BOUNDED."""
        context = TaskContext(input_results=None)
        result = await instrument.execute("Test query", context)

        assert result.outcome == Outcome.BOUNDED
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_empty_input_results_returns_bounded(self, instrument):
        """Empty input_results list returns Outcome.BOUNDED."""
        context = TaskContext(input_results=[])
        result = await instrument.execute("Test query", context)

        assert result.outcome == Outcome.BOUNDED
        assert result.confidence == 0.0
        assert len(result.suggested_followups) > 0


# ---------------------------------------------------------------------------
# TestConfidenceCalculation
# ---------------------------------------------------------------------------

class TestConfidenceCalculation:
    """Verify merged confidence calculation."""

    def test_weighted_average_by_finding_count(self):
        """Confidence is weighted by number of findings in each result."""
        # Result A: confidence 0.9, 2 findings → weight 2
        # Result B: confidence 0.6, 1 finding → weight 1
        # Expected: (0.9*2 + 0.6*1) / 3 = 0.8
        results = [
            _make_input_result(
                confidence=0.9,
                findings=[
                    {"content": "F1", "confidence": 0.9},
                    {"content": "F2", "confidence": 0.9},
                ],
            ),
            _make_input_result(
                confidence=0.6,
                findings=[{"content": "F3", "confidence": 0.6}],
            ),
        ]

        confidence = SynthesisInstrument._calculate_merged_confidence(results, [])

        assert abs(confidence - 0.8) < 0.001

    def test_agreement_bonus(self):
        """Two results with confidence >= 0.7 get +0.05 bonus."""
        results = [
            _make_input_result(confidence=0.8),
            _make_input_result(confidence=0.75),
        ]

        confidence = SynthesisInstrument._calculate_merged_confidence(results, [])

        # Base: (0.8 + 0.75) / 2 = 0.775, + 0.05 = 0.825
        assert abs(confidence - 0.825) < 0.001

    def test_no_agreement_bonus_when_low(self):
        """No bonus if any result has confidence < 0.7."""
        results = [
            _make_input_result(confidence=0.9),
            _make_input_result(confidence=0.5),
        ]

        confidence = SynthesisInstrument._calculate_merged_confidence(results, [])

        # Base: (0.9 + 0.5) / 2 = 0.7, no bonus
        assert abs(confidence - 0.7) < 0.001

    def test_confidence_capped_at_one(self):
        """Merged confidence cannot exceed 1.0."""
        results = [
            _make_input_result(confidence=0.98),
            _make_input_result(confidence=0.99),
        ]

        confidence = SynthesisInstrument._calculate_merged_confidence(results, [])

        assert confidence <= 1.0


# ---------------------------------------------------------------------------
# TestContradictionHandling
# ---------------------------------------------------------------------------

class TestContradictionHandling:
    """Verify contradiction detection and outcome adjustment."""

    @pytest.mark.asyncio
    async def test_no_contradictions_skips_analysis(self, instrument):
        """When no contradictions, analyze_discrepancy is not called."""
        context = TaskContext(input_results=[_make_input_result()])

        await instrument.execute("Test query", context)

        instrument.claude.analyze_discrepancy.assert_not_called()

    @pytest.mark.asyncio
    async def test_significant_yields_inconclusive(self, instrument):
        """Significant contradiction always yields INCONCLUSIVE."""
        instrument.claude.synthesize_with_analysis = AsyncMock(
            return_value=_contradiction_synthesis()
        )
        instrument.claude.analyze_discrepancy = AsyncMock(
            return_value=_discrepancy_analysis(severity="significant")
        )

        context = TaskContext(
            input_results=[
                _make_input_result(confidence=0.95),
                _make_input_result(confidence=0.95),
            ]
        )

        result = await instrument.execute("Test query", context)

        assert result.outcome == Outcome.INCONCLUSIVE
        assert result.discrepancy is not None

    @pytest.mark.asyncio
    async def test_minor_preserves_complete(self, instrument):
        """Minor contradiction keeps Outcome.COMPLETE."""
        instrument.claude.synthesize_with_analysis = AsyncMock(
            return_value=_contradiction_synthesis()
        )
        instrument.claude.analyze_discrepancy = AsyncMock(
            return_value=_discrepancy_analysis(severity="minor")
        )

        context = TaskContext(input_results=[_make_input_result(confidence=0.8)])

        result = await instrument.execute("Test query", context)

        assert result.outcome == Outcome.COMPLETE
        assert result.discrepancy is not None

    @pytest.mark.asyncio
    async def test_analysis_failure_graceful(self, instrument):
        """Exception in analyze_discrepancy falls back to COMPLETE."""
        instrument.claude.synthesize_with_analysis = AsyncMock(
            return_value=_contradiction_synthesis()
        )
        instrument.claude.analyze_discrepancy = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        context = TaskContext(input_results=[_make_input_result()])

        result = await instrument.execute("Test query", context)

        assert result.outcome == Outcome.COMPLETE
        assert result.discrepancy is None


# ---------------------------------------------------------------------------
# TestResynthesis
# ---------------------------------------------------------------------------

class TestResynthesis:
    """Verify re-synthesis on low confidence."""

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_resynthesis(self, instrument):
        """Confidence below threshold causes iteration count of 2."""
        context = TaskContext(
            input_results=[
                _make_input_result(confidence=0.4),
                _make_input_result(confidence=0.3),
            ]
        )

        result = await instrument.execute("Test query", context)

        assert result.iterations == 2
        assert instrument.claude.synthesize_with_analysis.call_count == 2

    @pytest.mark.asyncio
    async def test_resynthesis_bumps_confidence(self, instrument):
        """Re-synthesis adds 0.05 confidence bump."""
        context = TaskContext(
            input_results=[
                _make_input_result(confidence=0.4),
                _make_input_result(confidence=0.3),
            ]
        )

        result = await instrument.execute("Test query", context)

        # Base: (0.4 + 0.3) / 2 = 0.35, + 0.05 resynthesis bump = 0.40
        assert abs(result.confidence - 0.40) < 0.001

    @pytest.mark.asyncio
    async def test_high_confidence_no_resynthesis(self, instrument):
        """Confidence >= threshold means only 1 iteration."""
        context = TaskContext(
            input_results=[
                _make_input_result(confidence=0.8),
                _make_input_result(confidence=0.7),
            ]
        )

        result = await instrument.execute("Test query", context)

        assert result.iterations == 1
        assert instrument.claude.synthesize_with_analysis.call_count == 1
