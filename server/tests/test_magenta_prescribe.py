"""Tests for the Magenta Prescribe instrument."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.magenta.prescribe import PrescribeInstrument
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.db.client import DatabaseClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_claude():
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value='[{"diagnosis_type": "WEAK_HOOK", "title": "Improve opening hook", "description": "Start with a question", "specific_action": "Open next video with a provocative question in first 5 seconds", "reference_content_id": "top1"}]')
    return client


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DatabaseClient)
    db.get_top_performing_content = AsyncMock(return_value=[
        {"content_id": "top1", "title": "Best Video", "views": 50000, "avg_view_percentage": 70.0},
    ])
    db.list_prescriptions = AsyncMock(return_value=[])
    db.create_prescription = AsyncMock(return_value={})
    return db


@pytest.fixture
def sample_diagnose_output():
    return {
        "outcome": "complete",
        "findings": [{"content": '[{"diagnosis_type": "WEAK_HOOK"}]', "source": "magenta_diagnose"}],
        "summary": "Weak hook detected",
        "confidence": 0.85,
    }


# ---------------------------------------------------------------------------
# Capability Declarations
# ---------------------------------------------------------------------------


class TestPrescribeCapabilities:
    def test_name(self):
        assert PrescribeInstrument.name == "magenta_prescribe"

    def test_max_iterations(self):
        assert PrescribeInstrument.max_iterations == 1

    def test_required_capabilities(self):
        assert PrescribeInstrument.required_capabilities == frozenset({"reasoning"})


# ---------------------------------------------------------------------------
# Tool Injection
# ---------------------------------------------------------------------------


class TestPrescribeToolInjection:
    def test_accepts_injected_tools(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.prescribe.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.prescribe.DatabaseClient"):
            instrument = PrescribeInstrument(claude=mock_claude, db=mock_db)
            assert instrument.claude is mock_claude
            assert instrument.db is mock_db


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestPrescribeHappyPath:
    @pytest.mark.asyncio
    async def test_prescribe_with_diagnoses(self, mock_claude, mock_db, sample_diagnose_output):
        with patch("loop_symphony.instruments.magenta.prescribe.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.prescribe.DatabaseClient"):
            instrument = PrescribeInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_diagnose_output])
            result = await instrument.execute("Prescribe actions", context)

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 1
        assert result.confidence == 0.8
        assert len(result.findings) == 1
        assert result.findings[0].source == "magenta_prescribe"
        mock_claude.complete.assert_called_once()
        mock_db.create_prescription.assert_called_once()


# ---------------------------------------------------------------------------
# Missing Data
# ---------------------------------------------------------------------------


class TestPrescribeMissingData:
    @pytest.mark.asyncio
    async def test_no_context(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.prescribe.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.prescribe.DatabaseClient"):
            instrument = PrescribeInstrument(claude=mock_claude, db=mock_db)
            result = await instrument.execute("Prescribe actions", None)

        assert result.outcome == Outcome.INCONCLUSIVE

    @pytest.mark.asyncio
    async def test_empty_input_results(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.prescribe.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.prescribe.DatabaseClient"):
            instrument = PrescribeInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[])
            result = await instrument.execute("Prescribe actions", context)

        assert result.outcome == Outcome.INCONCLUSIVE


# ---------------------------------------------------------------------------
# DB Failure
# ---------------------------------------------------------------------------


class TestPrescribeDBFailure:
    @pytest.mark.asyncio
    async def test_top_content_fetch_failure_non_fatal(self, mock_claude, mock_db, sample_diagnose_output):
        mock_db.get_top_performing_content = AsyncMock(side_effect=Exception("DB error"))
        mock_db.list_prescriptions = AsyncMock(side_effect=Exception("DB error"))
        with patch("loop_symphony.instruments.magenta.prescribe.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.prescribe.DatabaseClient"):
            instrument = PrescribeInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_diagnose_output])
            result = await instrument.execute("Prescribe actions", context)

        assert result.outcome == Outcome.COMPLETE

    @pytest.mark.asyncio
    async def test_prescription_storage_failure_non_fatal(self, mock_claude, mock_db, sample_diagnose_output):
        mock_db.create_prescription = AsyncMock(side_effect=Exception("DB write error"))
        with patch("loop_symphony.instruments.magenta.prescribe.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.prescribe.DatabaseClient"):
            instrument = PrescribeInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_diagnose_output])
            result = await instrument.execute("Prescribe actions", context)

        assert result.outcome == Outcome.COMPLETE
