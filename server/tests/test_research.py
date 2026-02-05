"""Tests for Research instrument."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from loop_symphony.instruments.research import ResearchInstrument
from loop_symphony.models.outcome import Outcome
from loop_symphony.tools.tavily import SearchResponse, SearchResult


@pytest.fixture
def mock_settings():
    """Mock settings for tests."""
    with patch("loop_symphony.instruments.research.get_settings") as mock:
        settings = MagicMock()
        settings.research_max_iterations = 3
        settings.research_confidence_threshold = 0.8
        settings.research_confidence_delta_threshold = 0.05
        mock.return_value = settings
        yield settings


@pytest.fixture
def research_instrument(mock_settings):
    """Create a Research instrument with mocked dependencies."""
    with patch("loop_symphony.instruments.research.ClaudeClient") as mock_claude, \
         patch("loop_symphony.instruments.research.TavilyClient") as mock_tavily, \
         patch("loop_symphony.instruments.research.TerminationEvaluator") as mock_term:

        instrument = ResearchInstrument()
        instrument.claude = mock_claude.return_value
        instrument.tavily = mock_tavily.return_value
        instrument.termination = mock_term.return_value

        yield instrument


def _no_contradiction_synthesis(summary="Synthesized answer"):
    """Helper: mock synthesize_with_analysis returning no contradictions."""
    return AsyncMock(return_value={
        "summary": summary,
        "has_contradictions": False,
        "contradiction_hint": None,
    })


@pytest.mark.asyncio
async def test_research_execute_completes_on_confidence(research_instrument):
    """Test Research instrument terminates on high confidence."""
    # Setup mocks
    research_instrument.claude.complete = AsyncMock(side_effect=[
        "Research problem defined",  # Problem definition
        "query1\nquery2",  # Hypothesis generation
        "Follow-up 1\nFollow-up 2",  # Followups
    ])
    research_instrument.claude.synthesize_with_analysis = _no_contradiction_synthesis()

    research_instrument.tavily.search_multiple = AsyncMock(return_value=[
        SearchResponse(
            query="query1",
            results=[
                SearchResult(
                    title="Result 1",
                    url="https://example.com/1",
                    content="Content 1",
                    score=0.9,
                )
            ],
            answer="Direct answer from search",
        )
    ])

    # Mock termination to complete after first iteration
    from loop_symphony.termination.evaluator import TerminationResult
    research_instrument.termination.evaluate = MagicMock(return_value=TerminationResult(
        should_terminate=True,
        outcome=Outcome.COMPLETE,
        reason="Confidence converged",
    ))
    research_instrument.termination.calculate_confidence = MagicMock(return_value=0.85)

    result = await research_instrument.execute("Research latest AI developments")

    assert result.outcome == Outcome.COMPLETE
    assert result.confidence == 0.85
    assert len(result.findings) > 0


@pytest.mark.asyncio
async def test_research_execute_bounded_on_max_iterations(research_instrument):
    """Test Research instrument terminates on max iterations."""
    research_instrument.claude.complete = AsyncMock(return_value="query1\nquery2")
    research_instrument.claude.synthesize_with_analysis = _no_contradiction_synthesis("Summary")

    research_instrument.tavily.search_multiple = AsyncMock(return_value=[
        SearchResponse(query="q", results=[], answer=None)
    ])

    # Never terminate until bounds
    from loop_symphony.termination.evaluator import TerminationResult
    research_instrument.termination.evaluate = MagicMock(side_effect=[
        TerminationResult(should_terminate=False, outcome=None, reason="Continue"),
        TerminationResult(should_terminate=False, outcome=None, reason="Continue"),
        TerminationResult(
            should_terminate=True,
            outcome=Outcome.BOUNDED,
            reason="Reached max iterations",
        ),
    ])
    research_instrument.termination.calculate_confidence = MagicMock(return_value=0.5)

    result = await research_instrument.execute("Complex research query")

    assert result.outcome == Outcome.BOUNDED
    assert result.iterations == 3  # max_iterations from mock_settings


@pytest.mark.asyncio
async def test_research_accumulates_findings(research_instrument):
    """Test that Research instrument accumulates findings across iterations."""
    research_instrument.claude.complete = AsyncMock(return_value="query1")
    research_instrument.claude.synthesize_with_analysis = _no_contradiction_synthesis("Summary")

    # Return different results each call
    call_count = 0

    async def mock_search(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return [
            SearchResponse(
                query="q",
                results=[
                    SearchResult(
                        title=f"Result {call_count}",
                        url=f"https://example.com/{call_count}",
                        content=f"Content {call_count}",
                        score=0.8,
                    )
                ],
                answer=None,
            )
        ]

    research_instrument.tavily.search_multiple = mock_search

    from loop_symphony.termination.evaluator import TerminationResult
    research_instrument.termination.evaluate = MagicMock(side_effect=[
        TerminationResult(should_terminate=False, outcome=None, reason="Continue"),
        TerminationResult(
            should_terminate=True,
            outcome=Outcome.SATURATED,
            reason="No new findings",
        ),
    ])
    research_instrument.termination.calculate_confidence = MagicMock(return_value=0.7)

    result = await research_instrument.execute("Research query")

    # Should have findings from both iterations
    assert len(result.findings) >= 2
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_research_handles_search_failure(research_instrument):
    """Test Research instrument handles search failures gracefully."""
    research_instrument.claude.complete = AsyncMock(return_value="query1")
    research_instrument.claude.synthesize_with_analysis = _no_contradiction_synthesis(
        "Limited results"
    )

    # Simulate search failure
    research_instrument.tavily.search_multiple = AsyncMock(
        side_effect=Exception("Search API error")
    )

    from loop_symphony.termination.evaluator import TerminationResult
    research_instrument.termination.evaluate = MagicMock(return_value=TerminationResult(
        should_terminate=True,
        outcome=Outcome.SATURATED,
        reason="No findings",
    ))
    research_instrument.termination.calculate_confidence = MagicMock(return_value=0.0)

    # Should not raise, but return with empty findings
    result = await research_instrument.execute("Query that will fail")

    assert result.outcome == Outcome.SATURATED
    assert len(result.findings) == 0


@pytest.mark.asyncio
async def test_research_generates_followups(research_instrument):
    """Test Research instrument generates follow-up suggestions."""
    research_instrument.claude.complete = AsyncMock(side_effect=[
        "Problem statement",
        "query1",
        "Follow-up 1\nFollow-up 2\nFollow-up 3",
    ])
    research_instrument.claude.synthesize_with_analysis = _no_contradiction_synthesis("Summary")

    research_instrument.tavily.search_multiple = AsyncMock(return_value=[
        SearchResponse(query="q", results=[], answer="Answer")
    ])

    from loop_symphony.termination.evaluator import TerminationResult
    research_instrument.termination.evaluate = MagicMock(return_value=TerminationResult(
        should_terminate=True,
        outcome=Outcome.COMPLETE,
        reason="Done",
    ))
    research_instrument.termination.calculate_confidence = MagicMock(return_value=0.9)

    result = await research_instrument.execute("Research query")

    assert len(result.suggested_followups) <= 3


# --- Discrepancy detection tests ---


def _setup_single_iteration(research_instrument, confidence=0.85, outcome=Outcome.COMPLETE):
    """Helper: configure mocks for a single-iteration research loop."""
    research_instrument.claude.complete = AsyncMock(side_effect=[
        "Problem defined",   # _define_problem
        "query1",            # _generate_hypotheses
        "Followup 1\nFollowup 2",  # _suggest_followups (if called)
    ])

    research_instrument.tavily.search_multiple = AsyncMock(return_value=[
        SearchResponse(
            query="q",
            results=[
                SearchResult(
                    title="Result",
                    url="https://example.com/1",
                    content="Content",
                    score=0.9,
                )
            ],
            answer="Direct answer",
        )
    ])

    from loop_symphony.termination.evaluator import TerminationResult
    research_instrument.termination.evaluate = MagicMock(return_value=TerminationResult(
        should_terminate=True,
        outcome=outcome,
        reason="Done",
    ))
    research_instrument.termination.calculate_confidence = MagicMock(return_value=confidence)


@pytest.mark.asyncio
async def test_significant_discrepancy_yields_inconclusive(research_instrument):
    """Significant discrepancy → INCONCLUSIVE with populated discrepancy field."""
    _setup_single_iteration(research_instrument, confidence=0.85, outcome=Outcome.COMPLETE)

    research_instrument.claude.synthesize_with_analysis = AsyncMock(return_value={
        "summary": "Mixed results on coffee health.",
        "has_contradictions": True,
        "contradiction_hint": "Sources disagree on cardiovascular effects",
    })
    research_instrument.claude.analyze_discrepancy = AsyncMock(return_value={
        "description": "Fundamental disagreement on heart health impact",
        "severity": "significant",
        "conflicting_claims": ["Coffee is good", "Coffee is bad"],
        "suggested_refinements": ["Research coffee meta-analyses"],
    })

    result = await research_instrument.execute("Is coffee healthy?")

    assert result.outcome == Outcome.INCONCLUSIVE
    assert result.discrepancy == "Fundamental disagreement on heart health impact"


@pytest.mark.asyncio
async def test_minor_discrepancy_preserves_original_outcome(research_instrument):
    """Minor discrepancy → original outcome preserved with discrepancy as info."""
    _setup_single_iteration(research_instrument, confidence=0.85, outcome=Outcome.COMPLETE)

    research_instrument.claude.synthesize_with_analysis = AsyncMock(return_value={
        "summary": "Tokyo has about 14 million people.",
        "has_contradictions": True,
        "contradiction_hint": "Slight variance in reported population numbers",
    })
    research_instrument.claude.analyze_discrepancy = AsyncMock(return_value={
        "description": "Population figures vary between 13.9M and 14.1M",
        "severity": "minor",
        "conflicting_claims": ["13.9 million", "14.1 million"],
        "suggested_refinements": [],
    })

    result = await research_instrument.execute("Population of Tokyo")

    assert result.outcome == Outcome.COMPLETE
    assert result.discrepancy == "Population figures vary between 13.9M and 14.1M"


@pytest.mark.asyncio
async def test_moderate_high_confidence_stays_complete(research_instrument):
    """Moderate discrepancy + high confidence (>=0.9) → stays COMPLETE."""
    _setup_single_iteration(research_instrument, confidence=0.9, outcome=Outcome.COMPLETE)

    research_instrument.claude.synthesize_with_analysis = AsyncMock(return_value={
        "summary": "Summary with some disagreement.",
        "has_contradictions": True,
        "contradiction_hint": "Some moderate disagreement",
    })
    research_instrument.claude.analyze_discrepancy = AsyncMock(return_value={
        "description": "Moderate disagreement on timing",
        "severity": "moderate",
        "conflicting_claims": ["Claim A", "Claim B"],
        "suggested_refinements": [],
    })

    result = await research_instrument.execute("Test query")

    assert result.outcome == Outcome.COMPLETE
    assert result.discrepancy == "Moderate disagreement on timing"


@pytest.mark.asyncio
async def test_moderate_low_confidence_yields_inconclusive(research_instrument):
    """Moderate discrepancy + low confidence → INCONCLUSIVE."""
    _setup_single_iteration(research_instrument, confidence=0.7, outcome=Outcome.BOUNDED)

    research_instrument.claude.synthesize_with_analysis = AsyncMock(return_value={
        "summary": "Unclear results.",
        "has_contradictions": True,
        "contradiction_hint": "Moderate disagreement found",
    })
    research_instrument.claude.analyze_discrepancy = AsyncMock(return_value={
        "description": "Sources moderately disagree",
        "severity": "moderate",
        "conflicting_claims": ["X", "Y"],
        "suggested_refinements": ["Refine query A", "Refine query B"],
    })

    result = await research_instrument.execute("Test query")

    assert result.outcome == Outcome.INCONCLUSIVE
    assert result.discrepancy == "Sources moderately disagree"


@pytest.mark.asyncio
async def test_no_contradictions_skips_analyze(research_instrument):
    """No contradictions → analyze_discrepancy never called."""
    _setup_single_iteration(research_instrument, confidence=0.85, outcome=Outcome.COMPLETE)

    research_instrument.claude.synthesize_with_analysis = _no_contradiction_synthesis(
        "Clean summary"
    )
    research_instrument.claude.analyze_discrepancy = AsyncMock()

    result = await research_instrument.execute("Factual query")

    assert result.outcome == Outcome.COMPLETE
    assert result.discrepancy is None
    research_instrument.claude.analyze_discrepancy.assert_not_called()


@pytest.mark.asyncio
async def test_analysis_failure_graceful_fallback(research_instrument):
    """Analysis failure → graceful fallback, discrepancy=None, original outcome kept."""
    _setup_single_iteration(research_instrument, confidence=0.85, outcome=Outcome.COMPLETE)

    research_instrument.claude.synthesize_with_analysis = AsyncMock(return_value={
        "summary": "Summary.",
        "has_contradictions": True,
        "contradiction_hint": "Some contradiction",
    })
    research_instrument.claude.analyze_discrepancy = AsyncMock(
        side_effect=Exception("API error")
    )

    result = await research_instrument.execute("Test query")

    assert result.outcome == Outcome.COMPLETE
    assert result.discrepancy is None


@pytest.mark.asyncio
async def test_inconclusive_uses_refinements_as_followups(research_instrument):
    """INCONCLUSIVE uses refinements as followups (skips _suggest_followups)."""
    _setup_single_iteration(research_instrument, confidence=0.6, outcome=Outcome.BOUNDED)

    refinements = ["Try searching for X", "Look into Y specifically"]

    research_instrument.claude.synthesize_with_analysis = AsyncMock(return_value={
        "summary": "Contradictory results.",
        "has_contradictions": True,
        "contradiction_hint": "Major disagreement",
    })
    research_instrument.claude.analyze_discrepancy = AsyncMock(return_value={
        "description": "Significant conflict",
        "severity": "significant",
        "conflicting_claims": ["A", "B"],
        "suggested_refinements": refinements,
    })

    # Track whether _suggest_followups' claude.complete call is made
    # The side_effect list for complete only has enough entries for
    # _define_problem and _generate_hypotheses — if _suggest_followups
    # is called, it would consume the 3rd entry and we'd get the wrong result
    # or an error. So we verify by checking the followups directly.

    result = await research_instrument.execute("Controversial topic")

    assert result.outcome == Outcome.INCONCLUSIVE
    assert result.suggested_followups == refinements
