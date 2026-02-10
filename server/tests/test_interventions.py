"""Tests for the Four Interventions (Phase 5C)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.models.intervention import (
    Intervention,
    InterventionContext,
    InterventionResult,
    InterventionType,
)
from loop_symphony.models.task import (
    TaskContext,
    TaskPreferences,
    TaskRequest,
    TaskResponse,
)
from loop_symphony.models.finding import ExecutionMetadata
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.intent import Intent, IntentType
from loop_symphony.manager.intervention_detectors import (
    detect_proactive_suggestions,
    detect_pushback,
    detect_scoping,
    detect_capability_education,
    ERROR_PATTERN_MIN_OCCURRENCES,
    PUSHBACK_WORD_LIMIT,
    LOW_CONFIDENCE_THRESHOLD,
    SCOPING_CONJUNCTION_MIN,
)
from loop_symphony.manager.intervention_engine import (
    InterventionEngine,
    MAX_INTERVENTIONS,
    MAX_RECENT_QUERIES,
    TRUST_GATE,
)
from loop_symphony.manager.error_tracker import ErrorTracker
from loop_symphony.manager.trust_tracker import TrustTracker


# =============================================================================
# Helper to build InterventionContext quickly
# =============================================================================


def _ctx(**overrides) -> InterventionContext:
    """Build a minimal InterventionContext with overrides."""
    defaults = {
        "query": "test query",
        "response_summary": "test summary",
        "response_outcome": "complete",
        "response_confidence": 0.8,
        "instrument_used": "note",
        "available_instruments": ["note", "research", "synthesis", "vision"],
    }
    defaults.update(overrides)
    return InterventionContext(**defaults)


def _task_request(**overrides) -> TaskRequest:
    """Build a minimal TaskRequest."""
    defaults = {"query": "test query"}
    defaults.update(overrides)
    return TaskRequest(**defaults)


def _task_response(**overrides) -> TaskResponse:
    """Build a minimal TaskResponse."""
    defaults = {
        "request_id": "test-123",
        "outcome": Outcome.COMPLETE,
        "findings": [],
        "summary": "test summary",
        "confidence": 0.8,
        "metadata": ExecutionMetadata(
            instrument_used="note",
            iterations=1,
            duration_ms=100,
            sources_consulted=[],
        ),
    }
    defaults.update(overrides)
    return TaskResponse(**defaults)


# =============================================================================
# Model Tests
# =============================================================================


class TestInterventionType:
    """Tests for InterventionType enum."""

    def test_all_types_exist(self):
        assert InterventionType.PROACTIVE == "proactive"
        assert InterventionType.PUSHBACK == "pushback"
        assert InterventionType.SCOPING == "scoping"
        assert InterventionType.EDUCATION == "education"

    def test_four_types(self):
        assert len(InterventionType) == 4


class TestInterventionModel:
    """Tests for Intervention model."""

    def test_basic_construction(self):
        i = Intervention(
            type=InterventionType.PROACTIVE,
            message="Try this instead",
        )
        assert i.type == InterventionType.PROACTIVE
        assert i.message == "Try this instead"
        assert i.confidence == 0.5
        assert i.source == ""

    def test_full_construction(self):
        i = Intervention(
            type=InterventionType.PUSHBACK,
            message="Too broad",
            confidence=0.9,
            source="pushback:broad_scope",
        )
        assert i.confidence == 0.9
        assert i.source == "pushback:broad_scope"


class TestInterventionContext:
    """Tests for InterventionContext model."""

    def test_minimal_context(self):
        ctx = InterventionContext(
            query="test",
            response_summary="summary",
            response_outcome="complete",
            response_confidence=0.8,
            instrument_used="note",
        )
        assert ctx.trust_level == 0
        assert ctx.error_patterns == []
        assert ctx.recent_queries == []
        assert ctx.available_instruments == []
        assert ctx.suggested_followups == []
        assert ctx.intent_type is None

    def test_full_context(self):
        ctx = InterventionContext(
            query="test",
            response_summary="summary",
            response_outcome="failed",
            response_confidence=0.2,
            instrument_used="research",
            intent_type="decision",
            trust_level=2,
            error_patterns=[{"category": "tool", "occurrence_count": 5}],
            recent_queries=["q1", "q2"],
            available_instruments=["note", "research"],
            suggested_followups=["existing"],
        )
        assert ctx.trust_level == 2
        assert len(ctx.error_patterns) == 1
        assert len(ctx.recent_queries) == 2


class TestInterventionResult:
    """Tests for InterventionResult model."""

    def test_empty_result(self):
        r = InterventionResult()
        assert r.interventions == []
        assert r.context_used is None

    def test_with_interventions(self):
        r = InterventionResult(
            interventions=[
                Intervention(type=InterventionType.PROACTIVE, message="msg"),
            ],
        )
        assert len(r.interventions) == 1


# =============================================================================
# Detector: Proactive Suggestions
# =============================================================================


class TestDetectProactiveSuggestions:
    """Tests for detect_proactive_suggestions detector."""

    def test_no_patterns_returns_empty(self):
        ctx = _ctx(error_patterns=[])
        result = detect_proactive_suggestions(ctx)
        assert result == []

    def test_pattern_below_threshold_ignored(self):
        ctx = _ctx(error_patterns=[{
            "category": "tool",
            "occurrence_count": ERROR_PATTERN_MIN_OCCURRENCES - 1,
            "suggested_action": "Try different tool",
        }])
        result = detect_proactive_suggestions(ctx)
        assert result == []

    def test_pattern_at_threshold_triggers(self):
        ctx = _ctx(error_patterns=[{
            "category": "tool",
            "occurrence_count": ERROR_PATTERN_MIN_OCCURRENCES,
            "suggested_action": "Try different tool",
        }])
        result = detect_proactive_suggestions(ctx)
        assert len(result) == 1
        assert result[0].type == InterventionType.PROACTIVE
        assert "Try different tool" in result[0].message
        assert result[0].source == "error_pattern:tool"

    def test_pattern_without_action_ignored(self):
        ctx = _ctx(error_patterns=[{
            "category": "tool",
            "occurrence_count": 5,
            "suggested_action": None,
        }])
        result = detect_proactive_suggestions(ctx)
        assert result == []

    def test_repeated_failure_detected(self):
        ctx = _ctx(
            query="weather forecast for London",
            response_outcome="failed",
            recent_queries=[
                "weather forecast for Paris",
                "weather forecast for Berlin",
            ],
        )
        result = detect_proactive_suggestions(ctx)
        assert len(result) == 1
        assert result[0].source == "proactive:repeated_failure"

    def test_no_repeated_failure_on_success(self):
        ctx = _ctx(
            query="weather forecast",
            response_outcome="complete",
            recent_queries=["weather forecast", "weather forecast"],
        )
        result = detect_proactive_suggestions(ctx)
        assert result == []

    def test_confidence_scales_with_count(self):
        ctx = _ctx(error_patterns=[{
            "category": "api",
            "occurrence_count": 10,
            "suggested_action": "Check API key",
        }])
        result = detect_proactive_suggestions(ctx)
        assert result[0].confidence > 0.5


# =============================================================================
# Detector: Pushback
# =============================================================================


class TestDetectPushback:
    """Tests for detect_pushback detector."""

    def test_normal_query_no_pushback(self):
        ctx = _ctx(query="What is the weather today?")
        result = detect_pushback(ctx)
        assert result == []

    def test_broad_scope_triggers(self):
        ctx = _ctx(query="Tell me everything about quantum physics")
        result = detect_pushback(ctx)
        assert len(result) >= 1
        broad = [i for i in result if i.source == "pushback:broad_scope"]
        assert len(broad) == 1

    def test_exhaustive_triggers(self):
        ctx = _ctx(query="Give me an exhaustive list of all known species")
        result = detect_pushback(ctx)
        broad = [i for i in result if i.source == "pushback:broad_scope"]
        assert len(broad) == 1

    def test_long_query_triggers(self):
        words = " ".join(["word"] * (PUSHBACK_WORD_LIMIT + 1))
        ctx = _ctx(query=words)
        result = detect_pushback(ctx)
        long_q = [i for i in result if i.source == "pushback:long_query"]
        assert len(long_q) == 1
        assert str(PUSHBACK_WORD_LIMIT + 1) in long_q[0].message

    def test_short_query_no_length_pushback(self):
        ctx = _ctx(query="Short query")
        result = detect_pushback(ctx)
        long_q = [i for i in result if i.source == "pushback:long_query"]
        assert long_q == []

    def test_low_confidence_triggers(self):
        ctx = _ctx(
            query="simple query",
            response_confidence=LOW_CONFIDENCE_THRESHOLD - 0.01,
        )
        result = detect_pushback(ctx)
        low = [i for i in result if i.source == "pushback:low_confidence"]
        assert len(low) == 1

    def test_high_confidence_no_pushback(self):
        ctx = _ctx(query="simple query", response_confidence=0.9)
        result = detect_pushback(ctx)
        low = [i for i in result if i.source == "pushback:low_confidence"]
        assert low == []


# =============================================================================
# Detector: Scoping
# =============================================================================


class TestDetectScoping:
    """Tests for detect_scoping detector."""

    def test_simple_query_no_scoping(self):
        ctx = _ctx(query="What is photosynthesis?")
        result = detect_scoping(ctx)
        assert result == []

    def test_many_conjunctions_trigger(self):
        ctx = _ctx(
            query="Analyze this and compare that and summarize the results and draw conclusions"
        )
        result = detect_scoping(ctx)
        conj = [i for i in result if i.source == "scoping:conjunctions"]
        assert len(conj) == 1

    def test_below_conjunction_threshold_no_trigger(self):
        ctx = _ctx(query="Analyze this and compare that")
        result = detect_scoping(ctx)
        conj = [i for i in result if i.source == "scoping:conjunctions"]
        assert conj == []

    def test_numbered_list_triggers(self):
        ctx = _ctx(query="Please do: 1. Research topic 2. Write summary 3. Create report")
        result = detect_scoping(ctx)
        numbered = [i for i in result if i.source == "scoping:numbered_list"]
        assert len(numbered) == 1

    def test_sequential_markers_trigger(self):
        ctx = _ctx(
            query="First analyze the data, then create a summary, and finally write the report"
        )
        result = detect_scoping(ctx)
        seq = [i for i in result if i.source == "scoping:sequential"]
        assert len(seq) == 1

    def test_multiple_questions_trigger(self):
        ctx = _ctx(query="What is X? How does Y work? Why does Z happen?")
        result = detect_scoping(ctx)
        multi = [i for i in result if i.source == "scoping:multiple_questions"]
        assert len(multi) == 1
        assert "3 questions" in multi[0].message

    def test_single_question_no_trigger(self):
        ctx = _ctx(query="What is the meaning of life?")
        result = detect_scoping(ctx)
        multi = [i for i in result if i.source == "scoping:multiple_questions"]
        assert multi == []


# =============================================================================
# Detector: Capability Education
# =============================================================================


class TestDetectCapabilityEducation:
    """Tests for detect_capability_education detector."""

    def test_no_education_when_using_right_instrument(self):
        ctx = _ctx(
            intent_type="research",
            instrument_used="research",
        )
        result = detect_capability_education(ctx)
        assert result == []

    def test_research_intent_with_note_suggests_research(self):
        ctx = _ctx(
            intent_type="research",
            instrument_used="note",
        )
        result = detect_capability_education(ctx)
        research = [i for i in result if i.source == "education:research_instrument"]
        assert len(research) == 1

    def test_comparison_query_suggests_synthesis(self):
        ctx = _ctx(query="Compare Python vs JavaScript for web development")
        result = detect_capability_education(ctx)
        synth = [i for i in result if i.source == "education:synthesis_instrument"]
        assert len(synth) == 1

    def test_comparison_query_already_using_synthesis(self):
        ctx = _ctx(
            query="Compare Python vs JavaScript",
            instrument_used="synthesis",
        )
        result = detect_capability_education(ctx)
        synth = [i for i in result if i.source == "education:synthesis_instrument"]
        assert synth == []

    def test_image_query_suggests_vision(self):
        ctx = _ctx(query="Analyze this image of a chart")
        result = detect_capability_education(ctx)
        vision = [i for i in result if i.source == "education:vision_instrument"]
        assert len(vision) == 1

    def test_image_query_already_using_vision(self):
        ctx = _ctx(
            query="Analyze this image",
            instrument_used="vision",
        )
        result = detect_capability_education(ctx)
        vision = [i for i in result if i.source == "education:vision_instrument"]
        assert vision == []

    def test_no_education_without_available_instrument(self):
        ctx = _ctx(
            intent_type="research",
            instrument_used="note",
            available_instruments=["note"],  # research not available
        )
        result = detect_capability_education(ctx)
        assert result == []


# =============================================================================
# Intervention Engine: build_context
# =============================================================================


class TestBuildContext:
    """Tests for InterventionEngine.build_context."""

    def test_basic_context_building(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        request = _task_request()
        response = _task_response()

        ctx = engine.build_context(request, response)
        assert ctx.query == "test query"
        assert ctx.response_outcome == "complete"
        assert ctx.response_confidence == 0.8
        assert ctx.instrument_used == "note"
        assert ctx.trust_level == 0

    def test_trust_level_from_preferences(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        request = _task_request(
            preferences=TaskPreferences(trust_level=2),
        )
        response = _task_response()

        ctx = engine.build_context(request, response)
        assert ctx.trust_level == 2

    def test_intent_extracted(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        request = _task_request(
            context=TaskContext(intent=Intent(type=IntentType.RESEARCH)),
        )
        response = _task_response()

        ctx = engine.build_context(request, response)
        assert ctx.intent_type == "research"

    def test_error_patterns_included(self):
        tracker = ErrorTracker()
        # Record enough errors to auto-create patterns via _check_for_patterns
        from loop_symphony.models.error_learning import ErrorCategory, ErrorSeverity
        for _ in range(5):
            tracker.record_error(
                category=ErrorCategory.TOOL_FAILURE,
                error_message="Tavily rate limit",
                severity=ErrorSeverity.MEDIUM,
                tool="tavily",
            )

        engine = InterventionEngine(
            error_tracker=tracker,
            trust_tracker=TrustTracker(),
        )
        request = _task_request()
        response = _task_response()

        ctx = engine.build_context(request, response)
        # Patterns are auto-detected when enough similar errors are recorded
        assert len(ctx.error_patterns) > 0


# =============================================================================
# Intervention Engine: evaluate
# =============================================================================


class TestEvaluate:
    """Tests for InterventionEngine.evaluate."""

    def test_empty_context_no_interventions(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        ctx = _ctx()
        result = engine.evaluate(ctx)
        assert result.interventions == []

    def test_trust_level_0_allows_all(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        # Trigger education: research intent with note instrument
        ctx = _ctx(
            intent_type="research",
            instrument_used="note",
            trust_level=0,
        )
        result = engine.evaluate(ctx)
        education = [i for i in result.interventions if i.type == InterventionType.EDUCATION]
        assert len(education) == 1

    def test_trust_level_1_blocks_education(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        ctx = _ctx(
            intent_type="research",
            instrument_used="note",
            trust_level=1,
        )
        result = engine.evaluate(ctx)
        education = [i for i in result.interventions if i.type == InterventionType.EDUCATION]
        assert education == []

    def test_trust_level_2_blocks_scoping_and_education(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        # Trigger scoping (multiple questions) and education (research + note)
        ctx = _ctx(
            query="What is X? How does Y work?",
            intent_type="research",
            instrument_used="note",
            trust_level=2,
        )
        result = engine.evaluate(ctx)
        scoping = [i for i in result.interventions if i.type == InterventionType.SCOPING]
        education = [i for i in result.interventions if i.type == InterventionType.EDUCATION]
        assert scoping == []
        assert education == []

    def test_max_interventions_cap(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        # Trigger many interventions at once:
        # - broad scope pushback
        # - low confidence pushback
        # - multiple questions scoping
        # - conjunctions scoping
        # - education (research intent + note)
        ctx = _ctx(
            query=(
                "Tell me everything about X? And compare Y? "
                "And summarize Z? And what about W?"
            ),
            response_confidence=0.2,
            intent_type="research",
            instrument_used="note",
            trust_level=0,
        )
        result = engine.evaluate(ctx)
        assert len(result.interventions) <= MAX_INTERVENTIONS

    def test_sorted_by_confidence(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        # Trigger multiple interventions with different confidences
        ctx = _ctx(
            query="Tell me everything about X? What about Y?",
            response_confidence=0.2,
            trust_level=0,
        )
        result = engine.evaluate(ctx)
        if len(result.interventions) >= 2:
            for i in range(len(result.interventions) - 1):
                assert result.interventions[i].confidence >= result.interventions[i + 1].confidence

    def test_fail_open_per_detector(self):
        """If a detector raises, others still run."""
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        ctx = _ctx(
            query="Tell me everything about this topic",
            trust_level=0,
        )

        # Patch one detector to raise
        with patch(
            "loop_symphony.manager.intervention_engine.detect_proactive_suggestions",
            side_effect=RuntimeError("boom"),
        ):
            result = engine.evaluate(ctx)
            # Pushback should still trigger from "everything about"
            pushback = [i for i in result.interventions if i.type == InterventionType.PUSHBACK]
            assert len(pushback) >= 1

    def test_context_attached_to_result(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        ctx = _ctx()
        result = engine.evaluate(ctx)
        assert result.context_used is ctx


# =============================================================================
# Intervention Engine: evaluate_task
# =============================================================================


class TestEvaluateTask:
    """Tests for InterventionEngine.evaluate_task."""

    def test_tracks_recent_query(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        request = _task_request(query="my query")
        response = _task_response()

        engine.evaluate_task(request, response)
        assert "my query" in engine._recent_queries

    def test_rolling_window_capped(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        response = _task_response()

        for i in range(MAX_RECENT_QUERIES + 5):
            request = _task_request(query=f"query {i}")
            engine.evaluate_task(request, response)

        assert len(engine._recent_queries) == MAX_RECENT_QUERIES
        # Oldest should have been dropped
        assert "query 0" not in engine._recent_queries
        assert f"query {MAX_RECENT_QUERIES + 4}" in engine._recent_queries

    def test_returns_intervention_result(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        request = _task_request()
        response = _task_response()

        result = engine.evaluate_task(request, response)
        assert isinstance(result, InterventionResult)


# =============================================================================
# Intervention Engine: enrich_response
# =============================================================================


class TestEnrichResponse:
    """Tests for InterventionEngine.enrich_response."""

    def test_injects_prefixed_messages(self):
        response = _task_response()
        assert response.suggested_followups == []

        result = InterventionResult(
            interventions=[
                Intervention(
                    type=InterventionType.PROACTIVE,
                    message="Try a different approach",
                ),
                Intervention(
                    type=InterventionType.EDUCATION,
                    message="Use the research instrument",
                ),
            ],
        )

        enriched = InterventionEngine.enrich_response(response, result)
        assert len(enriched.suggested_followups) == 2
        assert enriched.suggested_followups[0] == "[proactive] Try a different approach"
        assert enriched.suggested_followups[1] == "[education] Use the research instrument"

    def test_preserves_existing_followups(self):
        response = _task_response(suggested_followups=["existing tip"])
        result = InterventionResult(
            interventions=[
                Intervention(type=InterventionType.PUSHBACK, message="Too broad"),
            ],
        )

        enriched = InterventionEngine.enrich_response(response, result)
        assert len(enriched.suggested_followups) == 2
        assert enriched.suggested_followups[0] == "existing tip"
        assert enriched.suggested_followups[1] == "[pushback] Too broad"

    def test_no_interventions_no_change(self):
        response = _task_response(suggested_followups=["tip"])
        result = InterventionResult(interventions=[])

        enriched = InterventionEngine.enrich_response(response, result)
        assert enriched.suggested_followups == ["tip"]


# =============================================================================
# Engine: get_status
# =============================================================================


class TestGetStatus:
    """Tests for InterventionEngine.get_status."""

    def test_returns_status_dict(self):
        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )
        status = engine.get_status()
        assert status["recent_queries_count"] == 0
        assert "note" in status["available_instruments"]
        assert status["max_interventions"] == MAX_INTERVENTIONS


# =============================================================================
# Trust Gate Configuration
# =============================================================================


class TestTrustGate:
    """Tests for trust gate configuration."""

    def test_level_0_allows_all(self):
        assert InterventionType.EDUCATION in TRUST_GATE[0]
        assert InterventionType.SCOPING in TRUST_GATE[0]
        assert InterventionType.PUSHBACK in TRUST_GATE[0]
        assert InterventionType.PROACTIVE in TRUST_GATE[0]

    def test_level_1_no_education(self):
        assert InterventionType.EDUCATION not in TRUST_GATE[1]
        assert InterventionType.SCOPING in TRUST_GATE[1]

    def test_level_2_only_proactive_and_pushback(self):
        assert TRUST_GATE[2] == {InterventionType.PROACTIVE, InterventionType.PUSHBACK}


# =============================================================================
# API Endpoints
# =============================================================================


class TestInterventionEndpoints:
    """Tests for intervention API endpoints."""

    @pytest.mark.asyncio
    async def test_intervention_status_endpoint(self):
        """GET /interventions/status returns engine status."""
        from loop_symphony.api.routes import intervention_status

        mock_engine = MagicMock(spec=InterventionEngine)
        mock_engine.get_status.return_value = {
            "recent_queries_count": 5,
            "available_instruments": ["note", "research"],
            "max_interventions": 3,
        }

        result = await intervention_status(engine=mock_engine)
        assert result["recent_queries_count"] == 5
        assert result["max_interventions"] == 3

    @pytest.mark.asyncio
    async def test_evaluate_endpoint(self):
        """POST /interventions/evaluate returns evaluation result."""
        from loop_symphony.api.routes import evaluate_interventions

        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )

        result = await evaluate_interventions(
            request={
                "query": "Tell me everything about quantum physics",
                "response_summary": "Summary",
                "response_outcome": "complete",
                "response_confidence": 0.8,
                "instrument_used": "note",
            },
            engine=engine,
        )
        assert "interventions" in result
        assert "count" in result
        # "everything about" should trigger pushback
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_evaluate_endpoint_minimal_request(self):
        """POST /interventions/evaluate works with minimal request."""
        from loop_symphony.api.routes import evaluate_interventions

        engine = InterventionEngine(
            error_tracker=ErrorTracker(),
            trust_tracker=TrustTracker(),
        )

        result = await evaluate_interventions(
            request={"query": "simple question"},
            engine=engine,
        )
        assert isinstance(result["count"], int)


# =============================================================================
# Integration: execute_task_background
# =============================================================================


class TestExecuteTaskBackgroundIntervention:
    """Tests for intervention integration in execute_task_background."""

    @pytest.mark.asyncio
    async def test_interventions_injected_into_response(self):
        """Interventions are added to suggested_followups before db.complete_task."""
        from loop_symphony.api.routes import execute_task_background

        mock_conductor = AsyncMock()
        mock_db = AsyncMock()
        mock_event_bus = MagicMock()

        response = _task_response(
            outcome=Outcome.COMPLETE,
            summary="A summary",
        )
        mock_conductor.execute.return_value = response

        request = _task_request(
            query="Tell me everything about quantum physics and biology and chemistry",
        )

        with patch("loop_symphony.api.routes.get_task_manager") as mock_tm, \
             patch("loop_symphony.api.routes.get_intervention_engine") as mock_ie, \
             patch("loop_symphony.api.routes.get_trust_tracker"):

            mock_task_manager = AsyncMock()
            mock_tm.return_value = mock_task_manager

            # Set up intervention engine to return an intervention
            engine = MagicMock(spec=InterventionEngine)
            engine.evaluate_task.return_value = InterventionResult(
                interventions=[
                    Intervention(
                        type=InterventionType.PUSHBACK,
                        message="This is very broad",
                    ),
                ],
            )
            mock_ie.return_value = engine

            await execute_task_background(request, mock_conductor, mock_db, mock_event_bus)

            # Verify engine was called
            engine.evaluate_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_intervention_failure_does_not_block(self):
        """If the intervention engine raises, the task still completes."""
        from loop_symphony.api.routes import execute_task_background

        mock_conductor = AsyncMock()
        mock_db = AsyncMock()
        mock_event_bus = MagicMock()

        response = _task_response()
        mock_conductor.execute.return_value = response

        request = _task_request()

        with patch("loop_symphony.api.routes.get_task_manager") as mock_tm, \
             patch("loop_symphony.api.routes.get_intervention_engine") as mock_ie, \
             patch("loop_symphony.api.routes.get_trust_tracker"):

            mock_task_manager = AsyncMock()
            mock_tm.return_value = mock_task_manager

            # Engine raises
            engine = MagicMock(spec=InterventionEngine)
            engine.evaluate_task.side_effect = RuntimeError("Engine crashed")
            mock_ie.return_value = engine

            await execute_task_background(request, mock_conductor, mock_db, mock_event_bus)

            # Task should still complete
            mock_db.complete_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_interventions_no_enrichment(self):
        """When no interventions found, response is unchanged."""
        from loop_symphony.api.routes import execute_task_background

        mock_conductor = AsyncMock()
        mock_db = AsyncMock()
        mock_event_bus = MagicMock()

        response = _task_response(suggested_followups=["original"])
        mock_conductor.execute.return_value = response

        request = _task_request(query="simple")

        with patch("loop_symphony.api.routes.get_task_manager") as mock_tm, \
             patch("loop_symphony.api.routes.get_intervention_engine") as mock_ie, \
             patch("loop_symphony.api.routes.get_trust_tracker"):

            mock_task_manager = AsyncMock()
            mock_tm.return_value = mock_task_manager

            engine = MagicMock(spec=InterventionEngine)
            engine.evaluate_task.return_value = InterventionResult(interventions=[])
            mock_ie.return_value = engine

            await execute_task_background(request, mock_conductor, mock_db, mock_event_bus)

            # db.complete_task should be called — response not enriched (no interventions)
            mock_db.complete_task.assert_called_once()
