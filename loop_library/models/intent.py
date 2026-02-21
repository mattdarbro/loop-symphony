"""Intent taxonomy for goal-aware task execution."""

from enum import Enum

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Primary intent categories."""

    DECISION = "decision"
    RESEARCH = "research"
    ACTION = "action"
    CURIOSITY = "curiosity"
    VALIDATION = "validation"


class UrgencyLevel(str, Enum):
    """How time-sensitive is this?"""

    IMMEDIATE = "immediate"
    SOON = "soon"
    PLANNING = "planning"
    EXPLORATORY = "exploratory"


class Intent(BaseModel):
    """Structured representation of user intent."""

    type: IntentType = IntentType.CURIOSITY
    urgency: UrgencyLevel = UrgencyLevel.EXPLORATORY
    success_criteria: str | None = None
    parent_goal_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    inferred: bool = False


INTENT_EXECUTION_HINTS: dict[IntentType, dict] = {
    IntentType.DECISION: {
        "needs_options": True,
        "needs_tradeoffs": True,
        "preferred_instrument": "research",
        "completion_check": "presents_clear_options",
    },
    IntentType.RESEARCH: {
        "needs_depth": True,
        "needs_sources": True,
        "preferred_instrument": "research",
        "completion_check": "comprehensive_coverage",
    },
    IntentType.ACTION: {
        "needs_steps": True,
        "needs_specificity": True,
        "preferred_instrument": "note",
        "completion_check": "actionable_steps",
    },
    IntentType.CURIOSITY: {
        "needs_depth": False,
        "preferred_instrument": "note",
        "completion_check": "answered_question",
    },
    IntentType.VALIDATION: {
        "needs_evidence": True,
        "needs_counterpoints": True,
        "preferred_instrument": "research",
        "completion_check": "evidence_presented",
    },
}


def infer_intent(query: str, goal: str | None = None) -> Intent:
    """Simple heuristic intent inference."""
    query_lower = query.lower()

    decision_signals = ["should i", "which is better", "compare", "vs", "or should", "choose between"]
    if any(signal in query_lower for signal in decision_signals):
        return Intent(type=IntentType.DECISION, inferred=True, confidence=0.8)

    action_signals = ["how do i", "how to", "steps to", "help me", "can you"]
    if any(signal in query_lower for signal in action_signals):
        return Intent(type=IntentType.ACTION, inferred=True, confidence=0.7)

    validation_signals = ["is it true", "am i right", "confirm", "verify", "fact check"]
    if any(signal in query_lower for signal in validation_signals):
        return Intent(type=IntentType.VALIDATION, inferred=True, confidence=0.8)

    research_signals = ["explain", "what is", "tell me about", "understand", "deep dive"]
    if any(signal in query_lower for signal in research_signals):
        return Intent(type=IntentType.RESEARCH, inferred=True, confidence=0.6)

    if goal:
        goal_lower = goal.lower()
        if "decide" in goal_lower or "choose" in goal_lower:
            return Intent(type=IntentType.DECISION, inferred=True, confidence=0.7)
        if "plan" in goal_lower:
            return Intent(type=IntentType.ACTION, inferred=True, confidence=0.6)

    return Intent(type=IntentType.CURIOSITY, inferred=True, confidence=0.5)
