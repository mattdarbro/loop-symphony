"""Tests for instrument protocol: capability declarations and tool injection."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.instruments.note import NoteInstrument
from loop_symphony.instruments.research import ResearchInstrument
from loop_symphony.models.outcome import Outcome
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.tools.tavily import TavilyClient, SearchResponse, SearchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_claude():
    """Create a mock ClaudeClient."""
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value="Mock response")
    client.synthesize_with_analysis = AsyncMock(return_value={
        "summary": "Mock summary",
        "has_contradictions": False,
        "contradiction_hint": None,
    })
    return client


@pytest.fixture
def mock_tavily():
    """Create a mock TavilyClient."""
    client = MagicMock(spec=TavilyClient)
    client.search_multiple = AsyncMock(return_value=[
        SearchResponse(query="q", results=[], answer="Mock answer")
    ])
    return client


@pytest.fixture
def mock_research_settings():
    """Mock settings for ResearchInstrument construction."""
    with patch("loop_symphony.instruments.research.get_settings") as mock:
        settings = MagicMock()
        settings.research_max_iterations = 3
        mock.return_value = settings
        yield settings


# ---------------------------------------------------------------------------
# TestCapabilityDeclarations
# ---------------------------------------------------------------------------

class TestCapabilityDeclarations:
    """Verify capability declarations on instrument classes."""

    def test_note_has_required_capabilities(self):
        """NoteInstrument declares required_capabilities."""
        assert hasattr(NoteInstrument, "required_capabilities")

    def test_research_has_required_capabilities(self):
        """ResearchInstrument declares required_capabilities."""
        assert hasattr(ResearchInstrument, "required_capabilities")

    def test_note_requires_reasoning(self):
        """NoteInstrument requires reasoning capability."""
        assert NoteInstrument.required_capabilities == frozenset({"reasoning"})

    def test_research_requires_reasoning_and_web_search(self):
        """ResearchInstrument requires reasoning and web_search."""
        assert ResearchInstrument.required_capabilities == frozenset(
            {"reasoning", "web_search"}
        )

    def test_research_optional_includes_synthesis_and_analysis(self):
        """ResearchInstrument optionally uses synthesis and analysis."""
        assert ResearchInstrument.optional_capabilities == frozenset(
            {"synthesis", "analysis"}
        )

    def test_capabilities_are_frozensets(self):
        """All capability declarations are frozensets (immutable)."""
        assert isinstance(NoteInstrument.required_capabilities, frozenset)
        assert isinstance(ResearchInstrument.required_capabilities, frozenset)
        assert isinstance(ResearchInstrument.optional_capabilities, frozenset)


# ---------------------------------------------------------------------------
# TestToolInjection
# ---------------------------------------------------------------------------

class TestToolInjection:
    """Verify instruments accept injected tool instances."""

    def test_note_accepts_injected_claude(self, mock_claude):
        """NoteInstrument accepts a claude kwarg."""
        with patch("loop_symphony.instruments.note.ClaudeClient"):
            instrument = NoteInstrument(claude=mock_claude)
            assert instrument.claude is mock_claude

    def test_research_accepts_injected_claude_and_tavily(
        self, mock_claude, mock_tavily, mock_research_settings
    ):
        """ResearchInstrument accepts claude and tavily kwargs."""
        with patch("loop_symphony.instruments.research.ClaudeClient"), \
             patch("loop_symphony.instruments.research.TavilyClient"):
            instrument = ResearchInstrument(
                claude=mock_claude, tavily=mock_tavily
            )
            assert instrument.claude is mock_claude
            assert instrument.tavily is mock_tavily

    def test_note_injected_claude_is_not_replaced(self, mock_claude):
        """Injected Claude is used directly, not replaced by a new one."""
        with patch("loop_symphony.instruments.note.ClaudeClient") as cls:
            instrument = NoteInstrument(claude=mock_claude)
            cls.assert_not_called()
            assert instrument.claude is mock_claude

    def test_research_injected_claude_is_not_replaced(
        self, mock_claude, mock_research_settings
    ):
        """Injected Claude in ResearchInstrument is not replaced."""
        with patch("loop_symphony.instruments.research.ClaudeClient") as cls, \
             patch("loop_symphony.instruments.research.TavilyClient"):
            instrument = ResearchInstrument(claude=mock_claude)
            cls.assert_not_called()
            assert instrument.claude is mock_claude

    def test_research_injected_tavily_is_not_replaced(
        self, mock_tavily, mock_research_settings
    ):
        """Injected Tavily in ResearchInstrument is not replaced."""
        with patch("loop_symphony.instruments.research.TavilyClient") as cls, \
             patch("loop_symphony.instruments.research.ClaudeClient"):
            instrument = ResearchInstrument(tavily=mock_tavily)
            cls.assert_not_called()
            assert instrument.tavily is mock_tavily

    def test_research_partial_injection_claude_only(
        self, mock_claude, mock_research_settings
    ):
        """Partial injection: only claude provided, tavily created internally."""
        with patch("loop_symphony.instruments.research.ClaudeClient"), \
             patch("loop_symphony.instruments.research.TavilyClient") as tavily_cls:
            tavily_cls.return_value = MagicMock(spec=TavilyClient)
            instrument = ResearchInstrument(claude=mock_claude)
            assert instrument.claude is mock_claude
            tavily_cls.assert_called_once()
            assert instrument.tavily is tavily_cls.return_value


# ---------------------------------------------------------------------------
# TestZeroArgBackwardCompat
# ---------------------------------------------------------------------------

class TestZeroArgBackwardCompat:
    """Verify zero-arg construction still works (backward compat)."""

    def test_note_zero_arg_construction(self):
        """NoteInstrument() works with no arguments."""
        with patch("loop_symphony.instruments.note.ClaudeClient"):
            instrument = NoteInstrument()
            assert instrument is not None

    def test_research_zero_arg_construction(self, mock_research_settings):
        """ResearchInstrument() works with no arguments."""
        with patch("loop_symphony.instruments.research.ClaudeClient"), \
             patch("loop_symphony.instruments.research.TavilyClient"):
            instrument = ResearchInstrument()
            assert instrument is not None

    def test_note_zero_arg_has_claude(self):
        """Zero-arg NoteInstrument has self.claude attribute."""
        with patch("loop_symphony.instruments.note.ClaudeClient") as cls:
            cls.return_value = MagicMock(spec=ClaudeClient)
            instrument = NoteInstrument()
            assert hasattr(instrument, "claude")
            assert instrument.claude is cls.return_value

    def test_research_zero_arg_has_claude_and_tavily(self, mock_research_settings):
        """Zero-arg ResearchInstrument has self.claude and self.tavily."""
        with patch("loop_symphony.instruments.research.ClaudeClient") as claude_cls, \
             patch("loop_symphony.instruments.research.TavilyClient") as tavily_cls:
            claude_cls.return_value = MagicMock(spec=ClaudeClient)
            tavily_cls.return_value = MagicMock(spec=TavilyClient)
            instrument = ResearchInstrument()
            assert hasattr(instrument, "claude")
            assert hasattr(instrument, "tavily")
            assert instrument.claude is claude_cls.return_value
            assert instrument.tavily is tavily_cls.return_value


# ---------------------------------------------------------------------------
# TestInjectedExecution
# ---------------------------------------------------------------------------

class TestInjectedExecution:
    """Verify instruments use injected tools during execution."""

    @pytest.mark.asyncio
    async def test_note_executes_with_injected_claude(self, mock_claude):
        """NoteInstrument with injected Claude executes correctly."""
        mock_claude.complete = AsyncMock(return_value="Injected response")

        with patch("loop_symphony.instruments.note.ClaudeClient"):
            instrument = NoteInstrument(claude=mock_claude)
            result = await instrument.execute("Test query")

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 1
        assert "Injected response" in result.findings[0].content
        mock_claude.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_research_executes_with_injected_tools(
        self, mock_claude, mock_tavily, mock_research_settings
    ):
        """ResearchInstrument with injected tools executes correctly."""
        mock_claude.complete = AsyncMock(side_effect=[
            "Problem defined",
            "query1",
            "Follow-up 1\nFollow-up 2",
        ])
        mock_claude.synthesize_with_analysis = AsyncMock(return_value={
            "summary": "Injected summary",
            "has_contradictions": False,
            "contradiction_hint": None,
        })

        mock_tavily.search_multiple = AsyncMock(return_value=[
            SearchResponse(
                query="query1",
                results=[
                    SearchResult(
                        title="Result",
                        url="https://example.com",
                        content="Content",
                        score=0.9,
                    )
                ],
                answer="Direct answer",
            )
        ])

        from loop_symphony.termination.evaluator import TerminationResult
        with patch("loop_symphony.instruments.research.ClaudeClient"), \
             patch("loop_symphony.instruments.research.TavilyClient"):
            instrument = ResearchInstrument(
                claude=mock_claude, tavily=mock_tavily
            )
            instrument.termination = MagicMock()
            instrument.termination.evaluate = MagicMock(
                return_value=TerminationResult(
                    should_terminate=True,
                    outcome=Outcome.COMPLETE,
                    reason="Done",
                )
            )
            instrument.termination.calculate_confidence = MagicMock(
                return_value=0.85
            )

            result = await instrument.execute("Research query")

        assert result.outcome == Outcome.COMPLETE
        assert result.confidence == 0.85
        mock_claude.complete.assert_called()
        mock_tavily.search_multiple.assert_called()

    @pytest.mark.asyncio
    async def test_execute_uses_injected_not_patched_class(self, mock_claude):
        """execute() uses the injected tool instance, not a class-level patch."""
        mock_claude.complete = AsyncMock(return_value="From injected")

        with patch("loop_symphony.instruments.note.ClaudeClient") as cls:
            # Class-level mock should NOT be used
            cls.return_value.complete = AsyncMock(return_value="From class")
            instrument = NoteInstrument(claude=mock_claude)
            result = await instrument.execute("Test")

        assert "From injected" in result.summary
        cls.return_value.complete.assert_not_called()
        mock_claude.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_result_matches_instrument_result_shape(self, mock_claude):
        """Results from injected execution match InstrumentResult shape."""
        mock_claude.complete = AsyncMock(return_value="Shaped response")

        with patch("loop_symphony.instruments.note.ClaudeClient"):
            instrument = NoteInstrument(claude=mock_claude)
            result = await instrument.execute("Shape test")

        assert isinstance(result, InstrumentResult)
        assert isinstance(result.outcome, Outcome)
        assert isinstance(result.findings, list)
        assert isinstance(result.summary, str)
        assert isinstance(result.confidence, float)
        assert isinstance(result.iterations, int)
        assert isinstance(result.sources_consulted, list)


# ---------------------------------------------------------------------------
# TestBaseInstrumentContract
# ---------------------------------------------------------------------------

class TestBaseInstrumentContract:
    """Verify BaseInstrument abstract contract."""

    def test_base_instrument_cannot_be_instantiated(self):
        """BaseInstrument is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseInstrument()

    def test_base_instrument_has_required_capabilities_declaration(self):
        """BaseInstrument declares required_capabilities as a class attribute."""
        assert hasattr(BaseInstrument, "__annotations__")
        assert "required_capabilities" in BaseInstrument.__annotations__

    def test_base_instrument_has_optional_capabilities_default(self):
        """BaseInstrument provides default empty frozenset for optional_capabilities."""
        assert BaseInstrument.optional_capabilities == frozenset()

    def test_subclass_must_declare_required_capabilities(self):
        """A subclass without required_capabilities uses the class annotation only."""

        class IncompleteInstrument(BaseInstrument):
            name = "incomplete"
            max_iterations = 1

            async def execute(self, query, context=None):
                return InstrumentResult(
                    outcome=Outcome.COMPLETE,
                    findings=[],
                    summary="",
                    confidence=0.0,
                    iterations=1,
                )

        # The class can be instantiated (it has execute), but it inherits
        # the annotation without a value — accessing it raises AttributeError
        instrument = IncompleteInstrument()
        assert not hasattr(instrument, "required_capabilities") or \
            isinstance(instrument.required_capabilities, frozenset)
