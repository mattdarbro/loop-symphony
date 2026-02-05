"""Tests for Termination Evaluator."""

import pytest
from unittest.mock import patch, MagicMock

from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.termination.evaluator import TerminationEvaluator


@pytest.fixture
def mock_settings():
    """Mock settings for tests."""
    with patch("loop_symphony.termination.evaluator.get_settings") as mock:
        settings = MagicMock()
        settings.research_confidence_threshold = 0.8
        settings.research_confidence_delta_threshold = 0.05
        mock.return_value = settings
        yield settings


@pytest.fixture
def evaluator(mock_settings):
    """Create a TerminationEvaluator with mocked settings."""
    return TerminationEvaluator()


class TestTerminationBounds:
    """Tests for bounds-based termination."""

    def test_terminates_at_max_iterations(self, evaluator):
        """Test termination when max iterations reached."""
        result = evaluator.evaluate(
            findings=[Finding(content="test")],
            iteration=5,
            max_iterations=5,
            confidence_history=[0.5, 0.6, 0.7, 0.75, 0.78],
        )

        assert result.should_terminate is True
        assert result.outcome == Outcome.BOUNDED
        assert "maximum iterations" in result.reason.lower()

    def test_continues_before_max_iterations(self, evaluator):
        """Test continuation when under max iterations."""
        result = evaluator.evaluate(
            findings=[Finding(content="test")],
            iteration=3,
            max_iterations=5,
            confidence_history=[0.5, 0.6, 0.7],
            previous_finding_count=0,
        )

        assert result.should_terminate is False
        assert result.outcome is None


class TestTerminationConfidence:
    """Tests for confidence-based termination."""

    def test_terminates_on_high_confidence_convergence(self, evaluator):
        """Test termination when confidence converges above threshold."""
        result = evaluator.evaluate(
            findings=[Finding(content="test")],
            iteration=3,
            max_iterations=5,
            confidence_history=[0.7, 0.85, 0.87],  # delta = 0.02 < 0.05
        )

        assert result.should_terminate is True
        assert result.outcome == Outcome.COMPLETE
        assert "converged" in result.reason.lower()

    def test_terminates_inconclusive_on_low_confidence_stall(self, evaluator):
        """Test inconclusive termination when confidence stalls at low level."""
        result = evaluator.evaluate(
            findings=[Finding(content="test")],
            iteration=4,
            max_iterations=5,
            confidence_history=[0.4, 0.42, 0.43, 0.44],  # All deltas < 0.05, below 0.8
        )

        assert result.should_terminate is True
        assert result.outcome == Outcome.INCONCLUSIVE
        assert "stalled" in result.reason.lower()

    def test_continues_on_increasing_confidence(self, evaluator):
        """Test continuation when confidence is still increasing significantly."""
        result = evaluator.evaluate(
            findings=[Finding(content="test1"), Finding(content="test2")],
            iteration=2,
            max_iterations=5,
            confidence_history=[0.5, 0.7],  # delta = 0.2 > 0.05
            previous_finding_count=1,
        )

        assert result.should_terminate is False


class TestTerminationSaturation:
    """Tests for saturation-based termination."""

    def test_terminates_on_no_new_findings(self, evaluator):
        """Test termination when no new findings discovered."""
        result = evaluator.evaluate(
            findings=[Finding(content="test")],
            iteration=3,
            max_iterations=5,
            confidence_history=[0.5, 0.6, 0.65],
            previous_finding_count=1,  # Same as current
        )

        assert result.should_terminate is True
        assert result.outcome == Outcome.SATURATED
        assert "no new findings" in result.reason.lower()

    def test_continues_on_new_findings(self, evaluator):
        """Test continuation when new findings are discovered."""
        result = evaluator.evaluate(
            findings=[Finding(content="test1"), Finding(content="test2")],
            iteration=2,
            max_iterations=5,
            confidence_history=[0.5, 0.55],
            previous_finding_count=1,  # Less than current (2)
        )

        assert result.should_terminate is False


class TestConfidenceCalculation:
    """Tests for confidence score calculation."""

    def test_zero_confidence_no_findings(self, evaluator):
        """Test zero confidence when no findings."""
        confidence = evaluator.calculate_confidence(
            findings=[],
            sources_count=0,
            has_answer=False,
        )

        assert confidence == 0.0

    def test_base_confidence_with_single_finding(self, evaluator):
        """Test base confidence with a single finding."""
        confidence = evaluator.calculate_confidence(
            findings=[Finding(content="test", confidence=1.0)],
            sources_count=1,
            has_answer=False,
        )

        # Base (0.3) + finding_boost (0.05) + source_boost (0.04) + confidence_boost (0.1)
        assert 0.4 <= confidence <= 0.6

    def test_high_confidence_with_answer(self, evaluator):
        """Test high confidence when direct answer found."""
        confidence = evaluator.calculate_confidence(
            findings=[
                Finding(content="test1", confidence=0.9),
                Finding(content="test2", confidence=0.9),
                Finding(content="test3", confidence=0.9),
            ],
            sources_count=5,
            has_answer=True,
        )

        # Should be close to max due to answer boost and multiple sources
        assert confidence >= 0.7

    def test_confidence_capped_at_one(self, evaluator):
        """Test that confidence is capped at 1.0."""
        confidence = evaluator.calculate_confidence(
            findings=[Finding(content=f"test{i}", confidence=1.0) for i in range(10)],
            sources_count=10,
            has_answer=True,
        )

        assert confidence <= 1.0
