"""Tests for the Magenta Diagnose instrument."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.magenta.diagnose import DiagnoseInstrument
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
    client.complete = AsyncMock(return_value='[{"diagnosis_type": "WEAK_HOOK", "severity": "high", "title": "Weak hook", "description": "First 30s losing viewers", "evidence": "retention drops 40% in first 30s", "metric_value": 0.3, "benchmark_value": 0.6}]')
    return client


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DatabaseClient)
    db.get_benchmarks = AsyncMock(return_value={
        "avg_view_percentage": 50.0,
        "avg_ctr": 5.0,
        "avg_subscriber_feed_ratio": 0.3,
        "avg_browse_traffic_ratio": 0.2,
    })
    return db


@pytest.fixture
def sample_ingest_output():
    return {
        "outcome": "complete",
        "findings": [{"content": '{"summary": "views up"}', "source": "magenta_ingest"}],
        "summary": '{"summary": "Views up 20%"}',
        "confidence": 0.9,
        "subscriber_count": 10000,
        "category": "education",
    }


# ---------------------------------------------------------------------------
# Capability Declarations
# ---------------------------------------------------------------------------


class TestDiagnoseCapabilities:
    def test_name(self):
        assert DiagnoseInstrument.name == "magenta_diagnose"

    def test_max_iterations(self):
        assert DiagnoseInstrument.max_iterations == 1

    def test_required_capabilities(self):
        assert DiagnoseInstrument.required_capabilities == frozenset({"reasoning"})


# ---------------------------------------------------------------------------
# Tool Injection
# ---------------------------------------------------------------------------


class TestDiagnoseToolInjection:
    def test_accepts_injected_tools(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.diagnose.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.diagnose.DatabaseClient"):
            instrument = DiagnoseInstrument(claude=mock_claude, db=mock_db)
            assert instrument.claude is mock_claude
            assert instrument.db is mock_db


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestDiagnoseHappyPath:
    @pytest.mark.asyncio
    async def test_diagnose_with_valid_ingest(self, mock_claude, mock_db, sample_ingest_output):
        with patch("loop_symphony.instruments.magenta.diagnose.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.diagnose.DatabaseClient"):
            instrument = DiagnoseInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_ingest_output])
            result = await instrument.execute("Diagnose content", context)

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 1
        assert result.confidence == 0.85
        assert len(result.findings) == 1
        assert result.findings[0].source == "magenta_diagnose"
        mock_claude.complete.assert_called_once()
        mock_db.get_benchmarks.assert_called_once()

    @pytest.mark.asyncio
    async def test_diagnose_without_benchmarks(self, mock_claude, mock_db, sample_ingest_output):
        mock_db.get_benchmarks = AsyncMock(return_value=None)
        with patch("loop_symphony.instruments.magenta.diagnose.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.diagnose.DatabaseClient"):
            instrument = DiagnoseInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_ingest_output])
            result = await instrument.execute("Diagnose content", context)

        assert result.outcome == Outcome.COMPLETE


# ---------------------------------------------------------------------------
# Missing Data
# ---------------------------------------------------------------------------


class TestDiagnoseMissingData:
    @pytest.mark.asyncio
    async def test_no_context(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.diagnose.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.diagnose.DatabaseClient"):
            instrument = DiagnoseInstrument(claude=mock_claude, db=mock_db)
            result = await instrument.execute("Diagnose content", None)

        assert result.outcome == Outcome.INCONCLUSIVE

    @pytest.mark.asyncio
    async def test_empty_input_results(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.diagnose.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.diagnose.DatabaseClient"):
            instrument = DiagnoseInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[])
            result = await instrument.execute("Diagnose content", context)

        assert result.outcome == Outcome.INCONCLUSIVE


# ---------------------------------------------------------------------------
# DB Failure
# ---------------------------------------------------------------------------


class TestDiagnoseDBFailure:
    @pytest.mark.asyncio
    async def test_benchmark_fetch_failure_non_fatal(self, mock_claude, mock_db, sample_ingest_output):
        mock_db.get_benchmarks = AsyncMock(side_effect=Exception("DB error"))
        with patch("loop_symphony.instruments.magenta.diagnose.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.diagnose.DatabaseClient"):
            instrument = DiagnoseInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_ingest_output])
            result = await instrument.execute("Diagnose content", context)

        assert result.outcome == Outcome.COMPLETE


# ---------------------------------------------------------------------------
# Subscriber Tier Logic
# ---------------------------------------------------------------------------


class TestSubscriberTier:
    def test_tier_0_1k(self):
        assert DiagnoseInstrument._determine_tier(500) == "0-1k"

    def test_tier_1k_10k(self):
        assert DiagnoseInstrument._determine_tier(5000) == "1k-10k"

    def test_tier_10k_100k(self):
        assert DiagnoseInstrument._determine_tier(50000) == "10k-100k"

    def test_tier_100k_1m(self):
        assert DiagnoseInstrument._determine_tier(500000) == "100k-1m"

    def test_tier_1m_plus(self):
        assert DiagnoseInstrument._determine_tier(2000000) == "1m+"
