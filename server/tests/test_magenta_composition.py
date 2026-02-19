"""Tests for the Magenta composition (full pipeline integration)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.instruments.magenta.composition import create_magenta_composition
from loop_symphony.instruments.magenta.diagnose import DiagnoseInstrument
from loop_symphony.instruments.magenta.ingest import IngestInstrument
from loop_symphony.instruments.magenta.prescribe import PrescribeInstrument
from loop_symphony.instruments.magenta.report import ReportInstrument
from loop_symphony.instruments.magenta.track import TrackInstrument
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext, TaskRequest
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.db.client import DatabaseClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_instrument(name: str, outcome: Outcome = Outcome.COMPLETE) -> MagicMock:
    """Create a mock instrument that returns a standard InstrumentResult."""
    instrument = MagicMock()
    instrument.name = name
    instrument.max_iterations = 1
    instrument.required_capabilities = frozenset({"reasoning"})
    instrument.execute = AsyncMock(return_value=InstrumentResult(
        outcome=outcome,
        findings=[Finding(content=f"Output from {name}", source=name)],
        summary=f"Summary from {name}",
        confidence=0.9,
        iterations=1,
        sources_consulted=[name],
    ))
    return instrument


@pytest.fixture
def mock_conductor():
    """Create a mock conductor with all 5 magenta instruments."""
    conductor = MagicMock()
    conductor.instruments = {
        "magenta_ingest": _make_mock_instrument("magenta_ingest"),
        "magenta_diagnose": _make_mock_instrument("magenta_diagnose"),
        "magenta_prescribe": _make_mock_instrument("magenta_prescribe"),
        "magenta_track": _make_mock_instrument("magenta_track"),
        "magenta_report": _make_mock_instrument("magenta_report"),
    }
    return conductor


# ---------------------------------------------------------------------------
# Composition Factory
# ---------------------------------------------------------------------------


class TestMagentaCompositionFactory:
    def test_creates_sequential_composition(self):
        composition = create_magenta_composition()
        assert composition is not None
        assert len(composition.steps) == 5

    def test_step_names(self):
        composition = create_magenta_composition()
        names = [name for name, _ in composition.steps]
        assert names == [
            "magenta_ingest",
            "magenta_diagnose",
            "magenta_prescribe",
            "magenta_track",
            "magenta_report",
        ]

    def test_composition_name(self):
        composition = create_magenta_composition()
        assert composition.name == (
            "magenta_ingest -> magenta_diagnose -> magenta_prescribe -> "
            "magenta_track -> magenta_report"
        )

    def test_all_configs_are_none(self):
        composition = create_magenta_composition()
        for _, config in composition.steps:
            assert config is None


# ---------------------------------------------------------------------------
# Full Pipeline Execution
# ---------------------------------------------------------------------------


class TestMagentaPipelineExecution:
    @pytest.mark.asyncio
    async def test_full_pipeline_happy_path(self, mock_conductor):
        composition = create_magenta_composition()
        context = TaskContext(
            input_results=[{
                "analytics": {
                    "content_id": "vid123",
                    "creator_id": "creator456",
                    "views": 5000,
                }
            }]
        )

        result = await composition.execute(
            "Analyze content", context, mock_conductor
        )

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 5  # 1 per stage
        # All 5 instruments should have been called
        for name in mock_conductor.instruments:
            mock_conductor.instruments[name].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_early_termination_on_inconclusive(self, mock_conductor):
        """If ingest returns INCONCLUSIVE, pipeline stops early."""
        mock_conductor.instruments["magenta_ingest"] = _make_mock_instrument(
            "magenta_ingest", outcome=Outcome.INCONCLUSIVE
        )

        composition = create_magenta_composition()
        context = TaskContext(input_results=[])

        result = await composition.execute(
            "Analyze content", context, mock_conductor
        )

        assert result.outcome == Outcome.INCONCLUSIVE
        assert result.iterations == 1
        # Only ingest should have been called
        mock_conductor.instruments["magenta_ingest"].execute.assert_called_once()
        mock_conductor.instruments["magenta_diagnose"].execute.assert_not_called()
        mock_conductor.instruments["magenta_prescribe"].execute.assert_not_called()
        mock_conductor.instruments["magenta_track"].execute.assert_not_called()
        mock_conductor.instruments["magenta_report"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_accumulated_sources(self, mock_conductor):
        composition = create_magenta_composition()
        context = TaskContext(
            input_results=[{
                "analytics": {
                    "content_id": "vid123",
                    "creator_id": "creator456",
                    "views": 5000,
                }
            }]
        )

        result = await composition.execute(
            "Analyze content", context, mock_conductor
        )

        # Sources from all 5 stages
        assert len(result.sources_consulted) == 5


# ---------------------------------------------------------------------------
# Conductor Integration
# ---------------------------------------------------------------------------


class TestConductorRouting:
    def test_magenta_keywords_route_correctly(self):
        """Verify MAGENTA_KEYWORDS exist in conductor module."""
        from loop_symphony.manager.conductor import MAGENTA_KEYWORDS
        assert "magenta" in MAGENTA_KEYWORDS
        assert "content analytics" in MAGENTA_KEYWORDS
        assert "youtube analytics" in MAGENTA_KEYWORDS

    def test_magenta_process_types(self):
        """Verify magenta instruments have CONSCIOUS process type."""
        from loop_symphony.manager.conductor import _INSTRUMENT_PROCESS_TYPE
        from loop_symphony.models.process import ProcessType

        for name in [
            "magenta_ingest",
            "magenta_diagnose",
            "magenta_prescribe",
            "magenta_track",
            "magenta_report",
        ]:
            assert _INSTRUMENT_PROCESS_TYPE[name] == ProcessType.CONSCIOUS
