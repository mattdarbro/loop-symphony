"""Tests for the Magenta Track instrument."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.magenta.track import TrackInstrument
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
    client.complete = AsyncMock(return_value='[{"prescription_id": "rx1", "effectiveness_score": 0.8, "summary": "Hook improvement worked", "learned_pattern": "Opening with a question increases retention by 15%", "is_effective": true}]')
    return client


@pytest.fixture
def mock_db():
    db = MagicMock(spec=DatabaseClient)
    db.get_applied_prescriptions_with_followups = AsyncMock(return_value=[
        {
            "id": "rx1",
            "creator_id": "creator456",
            "content_id": "vid_original",
            "followup_content_id": "vid_followup",
            "diagnosis_type": "WEAK_HOOK",
            "specific_action": "Start with a question",
        }
    ])
    db.list_creator_content = AsyncMock(return_value=[
        {"content_id": "vid_original", "views": 5000, "avg_view_percentage": 45.0},
        {"content_id": "vid_followup", "views": 8000, "avg_view_percentage": 62.0},
    ])
    db.update_prescription = AsyncMock(return_value={})
    db.create_knowledge_entry = AsyncMock(return_value={})
    return db


# ---------------------------------------------------------------------------
# Capability Declarations
# ---------------------------------------------------------------------------


class TestTrackCapabilities:
    def test_name(self):
        assert TrackInstrument.name == "magenta_track"

    def test_max_iterations(self):
        assert TrackInstrument.max_iterations == 1

    def test_required_capabilities(self):
        assert TrackInstrument.required_capabilities == frozenset({"reasoning"})


# ---------------------------------------------------------------------------
# Tool Injection
# ---------------------------------------------------------------------------


class TestTrackToolInjection:
    def test_accepts_injected_tools(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.track.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.track.DatabaseClient"):
            instrument = TrackInstrument(claude=mock_claude, db=mock_db)
            assert instrument.claude is mock_claude
            assert instrument.db is mock_db


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestTrackHappyPath:
    @pytest.mark.asyncio
    async def test_track_with_applied_prescriptions(self, mock_claude, mock_db):
        with patch("loop_symphony.instruments.magenta.track.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.track.DatabaseClient"):
            instrument = TrackInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(
                input_results=[{
                    "findings": [{"content": '{"creator_id": "creator456"}'}],
                }]
            )
            result = await instrument.execute("Track prescriptions", context)

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 1
        assert len(result.findings) == 1
        assert result.findings[0].source == "magenta_track"
        mock_claude.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_nothing_to_track(self, mock_claude, mock_db):
        """Graceful return when no applied prescriptions exist."""
        mock_db.get_applied_prescriptions_with_followups = AsyncMock(return_value=[])
        with patch("loop_symphony.instruments.magenta.track.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.track.DatabaseClient"):
            instrument = TrackInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(
                input_results=[{
                    "findings": [{"content": '{"creator_id": "creator456"}'}],
                }]
            )
            result = await instrument.execute("Track prescriptions", context)

        assert result.outcome == Outcome.COMPLETE
        assert "Nothing to track" in result.summary
        mock_claude.complete.assert_not_called()


# ---------------------------------------------------------------------------
# Missing Data
# ---------------------------------------------------------------------------


class TestTrackMissingData:
    @pytest.mark.asyncio
    async def test_no_creator_id(self, mock_claude, mock_db):
        """No creator_id extractable — returns nothing to track."""
        mock_db.get_applied_prescriptions_with_followups = AsyncMock(return_value=[])
        with patch("loop_symphony.instruments.magenta.track.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.track.DatabaseClient"):
            instrument = TrackInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(input_results=[{"summary": "no creator info"}])
            result = await instrument.execute("Track prescriptions", context)

        assert result.outcome == Outcome.COMPLETE
        assert "Nothing to track" in result.summary


# ---------------------------------------------------------------------------
# DB Failure
# ---------------------------------------------------------------------------


class TestTrackDBFailure:
    @pytest.mark.asyncio
    async def test_prescription_fetch_failure_non_fatal(self, mock_claude, mock_db):
        mock_db.get_applied_prescriptions_with_followups = AsyncMock(
            side_effect=Exception("DB error")
        )
        with patch("loop_symphony.instruments.magenta.track.ClaudeClient"), \
             patch("loop_symphony.instruments.magenta.track.DatabaseClient"):
            instrument = TrackInstrument(claude=mock_claude, db=mock_db)
            context = TaskContext(
                input_results=[{
                    "findings": [{"content": '{"creator_id": "creator456"}'}],
                }]
            )
            result = await instrument.execute("Track prescriptions", context)

        # Falls back to nothing-to-track when DB fails
        assert result.outcome == Outcome.COMPLETE
        assert "Nothing to track" in result.summary
