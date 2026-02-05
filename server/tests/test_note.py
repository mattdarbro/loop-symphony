"""Tests for Note instrument."""

import pytest
from unittest.mock import AsyncMock, patch

from loop_symphony.instruments.note import NoteInstrument
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext


@pytest.fixture
def note_instrument():
    """Create a Note instrument with mocked Claude client."""
    with patch("loop_symphony.instruments.note.ClaudeClient") as mock_claude:
        instrument = NoteInstrument()
        instrument.claude = mock_claude.return_value
        yield instrument


@pytest.mark.asyncio
async def test_note_execute_simple_query(note_instrument):
    """Test Note instrument with a simple query."""
    note_instrument.claude.complete = AsyncMock(return_value="Paris is the capital of France.")

    result = await note_instrument.execute("What is the capital of France?")

    assert result.outcome == Outcome.COMPLETE
    assert result.iterations == 1
    assert len(result.findings) == 1
    assert "Paris" in result.findings[0].content
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_note_execute_with_context(note_instrument):
    """Test Note instrument with task context."""
    note_instrument.claude.complete = AsyncMock(return_value="The weather in Tokyo is sunny.")

    context = TaskContext(
        user_id="user123",
        location="Tokyo",
        conversation_summary="User is planning a trip",
    )

    result = await note_instrument.execute("What's the weather like?", context)

    assert result.outcome == Outcome.COMPLETE
    assert result.iterations == 1
    # Verify context was passed to Claude
    call_args = note_instrument.claude.complete.call_args
    assert "Tokyo" in call_args[0][0] or "Tokyo" in str(call_args)


@pytest.mark.asyncio
async def test_note_always_single_iteration(note_instrument):
    """Test that Note always terminates after 1 iteration."""
    note_instrument.claude.complete = AsyncMock(return_value="Answer")

    result = await note_instrument.execute("Any question?")

    assert result.iterations == 1
    assert note_instrument.max_iterations == 1


@pytest.mark.asyncio
async def test_note_sources_consulted(note_instrument):
    """Test that Note reports Claude as the source."""
    note_instrument.claude.complete = AsyncMock(return_value="Answer")

    result = await note_instrument.execute("Question?")

    assert "claude" in result.sources_consulted
    assert result.findings[0].source == "claude"
