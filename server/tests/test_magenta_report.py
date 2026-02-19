"""Tests for the Magenta Report instrument."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.magenta.report import ReportInstrument
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
    client.complete = AsyncMock(return_value='{"title": "Weekly Performance Brief", "narrative": "Hey! Your latest video is doing great...", "diagnoses_count": 2, "prescriptions_count": 3, "tracking_summary": "1 past recommendation evaluated", "notification_title": "New Report", "notification_body": "Your weekly content report is ready."}')
    return client


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DatabaseClient)
    db.create_content_report = AsyncMock(return_value={})
    return db


@pytest.fixture
def sample_track_output():
    return {
        "outcome": "complete",
        "findings": [{"content": '{"creator_id": "creator456"}', "source": "magenta_track"}],
        "summary": "Tracking complete — 1 prescription evaluated",
        "confidence": 0.8,
    }


# ---------------------------------------------------------------------------
# Capability Declarations
# ---------------------------------------------------------------------------


class TestReportCapabilities:
    def test_name(self):
        assert ReportInstrument.name == "magenta_report"

    def test_max_iterations(self):
        assert ReportInstrument.max_iterations == 1

    def test_required_capabilities(self):
        assert ReportInstrument.required_capabilities == frozenset({"reasoning"})


# ---------------------------------------------------------------------------
# Tool Injection
# ---------------------------------------------------------------------------


class TestReportToolInjection:
    def test_accepts_injected_tools(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.report.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.report.DatabaseClient"):
            instrument = ReportInstrument(claude=mock_claude, db=mock_db)
            assert instrument.claude is mock_claude
            assert instrument.db is mock_db


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestReportHappyPath:
    @pytest.mark.asyncio
    async def test_report_generation(self, mock_claude, mock_db, sample_track_output):
        with patch("loop_symphony.instruments.magenta.report.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.report.DatabaseClient"):
            instrument = ReportInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(
                input_results=[sample_track_output],
                app_id="app1",
            )
            result = await instrument.execute("Generate report", context)

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 1
        assert result.confidence == 0.85
        assert len(result.findings) == 1
        assert result.findings[0].source == "magenta_report"
        mock_claude.complete.assert_called_once()
        mock_db.create_content_report.assert_called_once()


# ---------------------------------------------------------------------------
# Missing Data
# ---------------------------------------------------------------------------


class TestReportMissingData:
    @pytest.mark.asyncio
    async def test_no_context(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.report.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.report.DatabaseClient"):
            instrument = ReportInstrument(claude=mock_claude, db=mock_db)
            result = await instrument.execute("Generate report", None)

        assert result.outcome == Outcome.INCONCLUSIVE

    @pytest.mark.asyncio
    async def test_empty_input_results(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.report.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.report.DatabaseClient"):
            instrument = ReportInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[])
            result = await instrument.execute("Generate report", context)

        assert result.outcome == Outcome.INCONCLUSIVE


# ---------------------------------------------------------------------------
# DB Failure
# ---------------------------------------------------------------------------


class TestReportDBFailure:
    @pytest.mark.asyncio
    async def test_report_storage_failure_non_fatal(self, mock_claude, mock_db, sample_track_output):
        mock_db.create_content_report = AsyncMock(side_effect=Exception("DB error"))
        with patch("loop_symphony.instruments.magenta.report.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.report.DatabaseClient"):
            instrument = ReportInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_track_output])
            result = await instrument.execute("Generate report", context)

        assert result.outcome == Outcome.COMPLETE


# ---------------------------------------------------------------------------
# Report Type Determination
# ---------------------------------------------------------------------------


class TestReportType:
    def test_standard_report(self):
        output = {"summary": "Normal performance", "findings": []}
        assert ReportInstrument._determine_report_type(output) == "standard"

    def test_urgent_report(self):
        output = {
            "summary": "Performance issues",
            "findings": [{"content": "This is a critical issue with high severity"}],
        }
        assert ReportInstrument._determine_report_type(output) == "urgent"

    def test_weekly_report(self):
        output = {"summary": "weekly summary of performance", "findings": []}
        assert ReportInstrument._determine_report_type(output) == "weekly"
