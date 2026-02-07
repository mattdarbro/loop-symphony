"""Intent taxonomy for goal-aware task execution.

Understanding WHY the user is asking helps the system:
- Choose better arrangements (decision needs options, research needs depth)
- Evaluate completion (did we serve the goal, not just answer the question?)
- Learn patterns (this user + weather query → usually trip planning)
"""

from enum import Enum

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Primary intent categories."""

    DECISION = "decision"      # Help me choose between options
    RESEARCH = "research"      # Help me understand something deeply
    ACTION = "action"          # Help me do something / get steps
    CURIOSITY = "curiosity"    # I'm just wondering / no specific goal
    VALIDATION = "validation"  # Confirm or challenge what I think


class UrgencyLevel(str, Enum):
    """How time-sensitive is this?"""

    IMMEDIATE = "immediate"    # Need answer now
    SOON = "soon"              # Today or tomorrow
    PLANNING = "planning"      # Days/weeks out
    EXPLORATORY = "exploratory"  # No time pressure


class Intent(BaseModel):
    """Structured representation of user intent.

    Can be explicitly provided by iOS or inferred by the manager.
    """

    type: IntentType = IntentType.CURIOSITY
    urgency: UrgencyLevel = UrgencyLevel.EXPLORATORY

    # What does success look like for this intent?
    success_criteria: str | None = None  # e.g., "clear recommendation with reasoning"

    # Is this part of a larger ongoing goal?
    parent_goal_id: str | None = None  # Links to a multi-session goal

    # Confidence in this intent classification (if inferred)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    inferred: bool = False  # True if system guessed, False if user/iOS provided


# Maps intent types to execution hints
INTENT_EXECUTION_HINTS: dict[IntentType, dict] = {
    IntentType.DECISION: {
        "needs_options": True,
        "needs_tradeoffs": True,
        "preferred_instrument": "research",  # Gather options
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
        "preferred_instrument": "note",  # Often simpler
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
    """Simple heuristic intent inference.

    In production, this could use Claude for classification.
    For now, keyword-based heuristics.
    """
    query_lower = query.lower()

    # Decision signals
    decision_signals = ["should i", "which is better", "compare", "vs", "or should", "choose between"]
    if any(signal in query_lower for signal in decision_signals):
        return Intent(type=IntentType.DECISION, inferred=True, confidence=0.8)

    # Action signals
    action_signals = ["how do i", "how to", "steps to", "help me", "can you"]
    if any(signal in query_lower for signal in action_signals):
        return Intent(type=IntentType.ACTION, inferred=True, confidence=0.7)

    # Validation signals
    validation_signals = ["is it true", "am i right", "confirm", "verify", "fact check"]
    if any(signal in query_lower for signal in validation_signals):
        return Intent(type=IntentType.VALIDATION, inferred=True, confidence=0.8)

    # Research signals
    research_signals = ["explain", "what is", "tell me about", "understand", "deep dive"]
    if any(signal in query_lower for signal in research_signals):
        return Intent(type=IntentType.RESEARCH, inferred=True, confidence=0.6)

    # Goal context can shift interpretation
    if goal:
        goal_lower = goal.lower()
        if "decide" in goal_lower or "choose" in goal_lower:
            return Intent(type=IntentType.DECISION, inferred=True, confidence=0.7)
        if "plan" in goal_lower:
            return Intent(type=IntentType.ACTION, inferred=True, confidence=0.6)

    # Default to curiosity
    return Intent(type=IntentType.CURIOSITY, inferred=True, confidence=0.5)
