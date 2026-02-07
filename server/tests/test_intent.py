"""Tests for intent taxonomy."""

import pytest

from loop_symphony.models.intent import (
    Intent,
    IntentType,
    UrgencyLevel,
    INTENT_EXECUTION_HINTS,
    infer_intent,
)


class TestIntentType:
    """Tests for IntentType enum."""

    def test_values(self):
        assert IntentType.DECISION.value == "decision"
        assert IntentType.RESEARCH.value == "research"
        assert IntentType.ACTION.value == "action"
        assert IntentType.CURIOSITY.value == "curiosity"
        assert IntentType.VALIDATION.value == "validation"


class TestUrgencyLevel:
    """Tests for UrgencyLevel enum."""

    def test_values(self):
        assert UrgencyLevel.IMMEDIATE.value == "immediate"
        assert UrgencyLevel.SOON.value == "soon"
        assert UrgencyLevel.PLANNING.value == "planning"
        assert UrgencyLevel.EXPLORATORY.value == "exploratory"


class TestIntentModel:
    """Tests for Intent model."""

    def test_defaults(self):
        intent = Intent()
        assert intent.type == IntentType.CURIOSITY
        assert intent.urgency == UrgencyLevel.EXPLORATORY
        assert intent.confidence == 1.0
        assert intent.inferred is False

    def test_explicit_intent(self):
        intent = Intent(
            type=IntentType.DECISION,
            urgency=UrgencyLevel.SOON,
            success_criteria="clear recommendation",
        )
        assert intent.type == IntentType.DECISION
        assert intent.urgency == UrgencyLevel.SOON
        assert intent.success_criteria == "clear recommendation"

    def test_inferred_intent(self):
        intent = Intent(
            type=IntentType.ACTION,
            inferred=True,
            confidence=0.7,
        )
        assert intent.inferred is True
        assert intent.confidence == 0.7

    def test_parent_goal_link(self):
        intent = Intent(
            type=IntentType.RESEARCH,
            parent_goal_id="goal-123",
        )
        assert intent.parent_goal_id == "goal-123"


class TestInferIntent:
    """Tests for infer_intent function."""

    def test_decision_signals(self):
        queries = [
            "Should I buy a Tesla or Rivian?",
            "Which is better, Python or JavaScript?",
            "Compare iPhone vs Android",
        ]
        for query in queries:
            intent = infer_intent(query)
            assert intent.type == IntentType.DECISION
            assert intent.inferred is True

    def test_action_signals(self):
        queries = [
            "How do I set up a Python virtual environment?",
            "How to make pasta carbonara",
            "Help me write a cover letter",
        ]
        for query in queries:
            intent = infer_intent(query)
            assert intent.type == IntentType.ACTION
            assert intent.inferred is True

    def test_validation_signals(self):
        queries = [
            "Is it true that coffee stunts growth?",
            "Confirm that Python is dynamically typed",
            "Fact check: the moon affects tides",
        ]
        for query in queries:
            intent = infer_intent(query)
            assert intent.type == IntentType.VALIDATION
            assert intent.inferred is True

    def test_research_signals(self):
        queries = [
            "Explain quantum entanglement",
            "What is machine learning?",
            "Tell me about the Roman Empire",
        ]
        for query in queries:
            intent = infer_intent(query)
            assert intent.type == IntentType.RESEARCH
            assert intent.inferred is True

    def test_curiosity_default(self):
        intent = infer_intent("Weather today")
        assert intent.type == IntentType.CURIOSITY
        assert intent.confidence == 0.5

    def test_goal_context_decision(self):
        intent = infer_intent("weather in tokyo", goal="decide when to visit")
        assert intent.type == IntentType.DECISION

    def test_goal_context_action(self):
        intent = infer_intent("weather in tokyo", goal="plan my trip")
        assert intent.type == IntentType.ACTION


class TestExecutionHints:
    """Tests for INTENT_EXECUTION_HINTS mapping."""

    def test_decision_hints(self):
        hints = INTENT_EXECUTION_HINTS[IntentType.DECISION]
        assert hints["needs_options"] is True
        assert hints["needs_tradeoffs"] is True

    def test_research_hints(self):
        hints = INTENT_EXECUTION_HINTS[IntentType.RESEARCH]
        assert hints["needs_depth"] is True
        assert hints["needs_sources"] is True

    def test_action_hints(self):
        hints = INTENT_EXECUTION_HINTS[IntentType.ACTION]
        assert hints["needs_steps"] is True
        assert hints["needs_specificity"] is True

    def test_all_intents_have_hints(self):
        for intent_type in IntentType:
            assert intent_type in INTENT_EXECUTION_HINTS
