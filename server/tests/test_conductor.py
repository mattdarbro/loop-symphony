"""Tests for Conductor routing logic."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from loop_symphony.manager.conductor import Conductor
from loop_symphony.models.task import TaskRequest, TaskPreferences


@pytest.fixture
def conductor():
    """Create a Conductor with mocked instruments."""
    with patch("loop_symphony.manager.conductor.NoteInstrument") as mock_note, \
         patch("loop_symphony.manager.conductor.ResearchInstrument") as mock_research, \
         patch("loop_symphony.manager.conductor.SynthesisInstrument") as mock_synthesis, \
         patch("loop_symphony.manager.conductor.VisionInstrument") as mock_vision, \
         patch("loop_symphony.manager.conductor.IngestInstrument"), \
         patch("loop_symphony.manager.conductor.DiagnoseInstrument"), \
         patch("loop_symphony.manager.conductor.PrescribeInstrument"), \
         patch("loop_symphony.manager.conductor.TrackInstrument"), \
         patch("loop_symphony.manager.conductor.ReportInstrument"):

        cond = Conductor()
        # Replace instruments with mocks
        cond.instruments["note"] = mock_note.return_value
        cond.instruments["research"] = mock_research.return_value
        cond.instruments["synthesis"] = mock_synthesis.return_value
        cond.instruments["vision"] = mock_vision.return_value
        yield cond


class TestRoutingLogic:
    """Tests for task routing logic."""

    @pytest.mark.asyncio
    async def test_routes_simple_query_to_note(self, conductor):
        """Test that simple queries are routed to note instrument."""
        request = TaskRequest(query="What is 2 + 2?")

        instrument = await conductor.analyze_and_route(request)

        assert instrument == "note"

    @pytest.mark.asyncio
    async def test_routes_research_keyword_to_research(self, conductor):
        """Test that research keywords route to research instrument."""
        research_queries = [
            "Research the latest developments in AI",
            "Find information about quantum computing",
            "Search for Python best practices",
            "Investigate the causes of climate change",
            "What are the latest news about SpaceX?",
            "Compare Python vs JavaScript for web development",
        ]

        for query in research_queries:
            request = TaskRequest(query=query)
            instrument = await conductor.analyze_and_route(request)
            assert instrument == "research", f"Query '{query}' should route to research"

    @pytest.mark.asyncio
    async def test_routes_complex_query_to_research(self, conductor):
        """Test that complex queries are routed to research."""
        complex_queries = [
            "What are the pros and cons of using React vs Vue?",
            "Explain the difference between SQL and NoSQL databases",
            "Python vs JavaScript: which should I learn first?",
        ]

        for query in complex_queries:
            request = TaskRequest(query=query)
            instrument = await conductor.analyze_and_route(request)
            assert instrument == "research", f"Query '{query}' should route to research"

    @pytest.mark.asyncio
    async def test_routes_long_query_to_research(self, conductor):
        """Test that long queries are routed to research."""
        long_query = " ".join(["word"] * 25)  # 25 words
        request = TaskRequest(query=long_query)

        instrument = await conductor.analyze_and_route(request)

        assert instrument == "research"

    @pytest.mark.asyncio
    async def test_routes_multiple_questions_to_research(self, conductor):
        """Test that multiple questions route to research."""
        request = TaskRequest(query="What is Python? How do I install it?")

        instrument = await conductor.analyze_and_route(request)

        assert instrument == "research"

    @pytest.mark.asyncio
    async def test_thorough_preference_routes_to_research(self, conductor):
        """Test that thorough preference routes to research."""
        request = TaskRequest(
            query="What is Python?",
            preferences=TaskPreferences(thoroughness="thorough"),
        )

        instrument = await conductor.analyze_and_route(request)

        assert instrument == "research"

    @pytest.mark.asyncio
    async def test_quick_preference_allows_note(self, conductor):
        """Test that quick preference allows note routing."""
        request = TaskRequest(
            query="What is the capital of France?",
            preferences=TaskPreferences(thoroughness="quick"),
        )

        instrument = await conductor.analyze_and_route(request)

        assert instrument == "note"


class TestExecution:
    """Tests for task execution."""

    @pytest.mark.asyncio
    async def test_execute_calls_correct_instrument(self, conductor):
        """Test that execute calls the routed instrument."""
        from loop_symphony.instruments.base import InstrumentResult
        from loop_symphony.models.outcome import Outcome
        from loop_symphony.models.finding import Finding

        # Setup mock return value
        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[Finding(content="Answer")],
            summary="The answer",
            confidence=0.9,
            iterations=1,
        )
        conductor.instruments["note"].execute = AsyncMock(return_value=mock_result)

        request = TaskRequest(query="Simple question?")
        response = await conductor.execute(request)

        assert response.outcome == Outcome.COMPLETE
        assert response.metadata.instrument_used == "note"
        conductor.instruments["note"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_includes_metadata(self, conductor):
        """Test that execute includes proper metadata."""
        from loop_symphony.instruments.base import InstrumentResult
        from loop_symphony.models.outcome import Outcome
        from loop_symphony.models.finding import Finding

        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[Finding(content="Answer")],
            summary="The answer",
            confidence=0.9,
            iterations=3,
            sources_consulted=["source1", "source2"],
        )
        conductor.instruments["research"].execute = AsyncMock(return_value=mock_result)

        request = TaskRequest(query="Research something")
        response = await conductor.execute(request)

        assert response.metadata.instrument_used == "research"
        assert response.metadata.iterations == 3
        assert response.metadata.duration_ms >= 0
        assert "source1" in response.metadata.sources_consulted
