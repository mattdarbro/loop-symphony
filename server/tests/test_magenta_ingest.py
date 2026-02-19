"""Tests for the Magenta Ingest instrument."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.magenta.ingest import IngestInstrument
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
    client.complete = AsyncMock(return_value='{"summary": "Views up 20%", "trends": ["growing"], "notable_changes": []}')
    return client


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DatabaseClient)
    db.upsert_content_performance = AsyncMock(return_value={})
    db.list_creator_content = AsyncMock(return_value=[
        {"content_id": "old1", "title": "Old Video", "views": 1000, "avg_view_percentage": 45.0},
    ])
    return db


@pytest.fixture
def sample_analytics():
    return {
        "content_id": "vid123",
        "creator_id": "creator456",
        "views": 5000,
        "likes": 300,
        "comments": 50,
        "avg_view_duration_seconds": 180.0,
        "avg_view_percentage": 55.0,
        "subscriber_count": 10000,
        "impressions": 50000,
        "impression_click_through_rate": 5.5,
    }


# ---------------------------------------------------------------------------
# Capability Declarations
# ---------------------------------------------------------------------------


class TestIngestCapabilities:
    def test_name(self):
        assert IngestInstrument.name == "magenta_ingest"

    def test_max_iterations(self):
        assert IngestInstrument.max_iterations == 1

    def test_required_capabilities(self):
        assert IngestInstrument.required_capabilities == frozenset({"reasoning"})


# ---------------------------------------------------------------------------
# Tool Injection
# ---------------------------------------------------------------------------


class TestIngestToolInjection:
    def test_accepts_injected_claude(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            assert instrument.claude is mock_claude
            assert instrument.db is mock_db


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestIngestHappyPath:
    @pytest.mark.asyncio
    async def test_ingest_with_valid_data(self, mock_claude, mock_db, sample_analytics):
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(
                input_results=[{"analytics": sample_analytics}],
                app_id="app1",
            )
            result = await instrument.execute("Analyze content", context)

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 1
        assert result.confidence == 0.9
        assert len(result.findings) == 1
        assert result.findings[0].source == "magenta_ingest"
        mock_claude.complete.assert_called_once()
        mock_db.upsert_content_performance.assert_called_once()
        mock_db.list_creator_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_flat_analytics(self, mock_claude, mock_db, sample_analytics):
        """Analytics data provided flat (not wrapped in 'analytics' key)."""
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[sample_analytics])
            result = await instrument.execute("Analyze content", context)

        assert result.outcome == Outcome.COMPLETE


# ---------------------------------------------------------------------------
# Missing / Invalid Data
# ---------------------------------------------------------------------------


class TestIngestMissingData:
    @pytest.mark.asyncio
    async def test_no_context(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            result = await instrument.execute("Analyze content", None)

        assert result.outcome == Outcome.INCONCLUSIVE
        mock_claude.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_input_results(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[])
            result = await instrument.execute("Analyze content", context)

        assert result.outcome == Outcome.INCONCLUSIVE

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            # Missing content_id and creator_id
            context = TaskContext(input_results=[{"views": 100}])
            result = await instrument.execute("Analyze content", context)

        assert result.outcome == Outcome.INCONCLUSIVE
        assert "Missing required fields" in result.summary


# ---------------------------------------------------------------------------
# DB Failure Handling
# ---------------------------------------------------------------------------


class TestIngestDBFailure:
    @pytest.mark.asyncio
    async def test_db_upsert_failure_non_fatal(self, mock_claude, mock_db, sample_analytics):
        mock_db.upsert_content_performance = AsyncMock(side_effect=Exception("DB down"))
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[{"analytics": sample_analytics}])
            result = await instrument.execute("Analyze content", context)

        # Should still complete even if DB upsert fails
        assert result.outcome == Outcome.COMPLETE
        mock_claude.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_history_failure_non_fatal(self, mock_claude, mock_db, sample_analytics):
        mock_db.list_creator_content = AsyncMock(side_effect=Exception("DB down"))
        with patch("loop_symphony.instruments.magenta.ingest.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.ingest.DatabaseClient"):
            instrument = IngestInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[{"analytics": sample_analytics}])
            result = await instrument.execute("Analyze content", context)

        assert result.outcome == Outcome.COMPLETE
