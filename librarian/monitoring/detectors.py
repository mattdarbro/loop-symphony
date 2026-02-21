"""Intervention detector functions (Phase 5C).

Four pure functions that inspect an InterventionContext and return
a list of Intervention suggestions. Each function is independent
and fail-safe — callers wrap in try/except.
"""

import re

from librarian.monitoring.models import Intervention, InterventionContext, InterventionType

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
ERROR_PATTERN_MIN_OCCURRENCES = 3
PUSHBACK_WORD_LIMIT = 100
LOW_CONFIDENCE_THRESHOLD = 0.3
SCOPING_CONJUNCTION_MIN = 3


def detect_proactive_suggestions(ctx: InterventionContext) -> list[Intervention]:
    """Detect recurring pain points from error patterns.

    Triggers:
    - Error patterns with occurrence_count >= 3 that have a suggested_action
    - Failed outcomes on queries similar to recent failures
    """
    interventions: list[Intervention] = []

    # Check error patterns with actionable suggestions
    for pattern in ctx.error_patterns:
        count = pattern.get("occurrence_count", 0)
        action = pattern.get("suggested_action")
        category = pattern.get("category", "unknown")

        if count >= ERROR_PATTERN_MIN_OCCURRENCES and action:
            interventions.append(Intervention(
                type=InterventionType.PROACTIVE,
                message=f"Recurring issue detected: {action}",
                confidence=min(0.9, 0.5 + count * 0.05),
                source=f"error_pattern:{category}",
            ))

    # Check for failed outcome with prior similar queries
    if ctx.response_outcome == "failed" and ctx.recent_queries:
        query_lower = ctx.query.lower()
        similar_count = sum(
            1 for q in ctx.recent_queries
            if _query_similarity(query_lower, q.lower()) > 0.5
        )
        if similar_count >= 2:
            interventions.append(Intervention(
                type=InterventionType.PROACTIVE,
                message=(
                    "This type of query has failed before. "
                    "Consider rephrasing or breaking it into simpler parts."
                ),
                confidence=0.6,
                source="proactive:repeated_failure",
            ))

    return interventions


def detect_pushback(ctx: InterventionContext) -> list[Intervention]:
    """Detect unrealistic or overly broad requests.

    Triggers:
    - Scope-inflating phrases ("everything about", "complete analysis of all")
    - Very long queries (> 100 words)
    - Very low response confidence (< 0.3)
    """
    interventions: list[Intervention] = []
    query_lower = ctx.query.lower()

    # Check for overly broad scope phrases
    broad_patterns = [
        r"\beverything\s+about\b",
        r"\bcomplete\s+analysis\s+of\s+all\b",
        r"\ball\s+possible\b",
        r"\bevery\s+aspect\s+of\b",
        r"\bexhaustive\b",
    ]
    for pattern in broad_patterns:
        if re.search(pattern, query_lower):
            interventions.append(Intervention(
                type=InterventionType.PUSHBACK,
                message=(
                    "This request is very broad. Consider focusing on "
                    "a specific aspect for better results."
                ),
                confidence=0.7,
                source="pushback:broad_scope",
            ))
            break  # One pushback for broad scope is enough

    # Check for very long queries
    word_count = len(ctx.query.split())
    if word_count > PUSHBACK_WORD_LIMIT:
        interventions.append(Intervention(
            type=InterventionType.PUSHBACK,
            message=(
                f"Your request is {word_count} words long. "
                "Consider splitting it into focused sub-requests."
            ),
            confidence=0.6,
            source="pushback:long_query",
        ))

    # Check for low confidence response
    if ctx.response_confidence < LOW_CONFIDENCE_THRESHOLD:
        interventions.append(Intervention(
            type=InterventionType.PUSHBACK,
            message=(
                "The response confidence is low. The request may be "
                "too ambitious — try narrowing the scope."
            ),
            confidence=0.5,
            source="pushback:low_confidence",
        ))

    return interventions


def detect_scoping(ctx: InterventionContext) -> list[Intervention]:
    """Detect requests that need decomposition.

    Triggers:
    - Multiple conjunctions suggesting compound sub-tasks
    - Numbered list patterns
    - Multiple question marks
    """
    interventions: list[Intervention] = []
    query_lower = ctx.query.lower()

    # Count conjunctions that separate distinct tasks
    # Look for " and " as a conjunction (not "and" within words)
    conjunction_count = len(re.findall(r"\band\b", query_lower))
    if conjunction_count >= SCOPING_CONJUNCTION_MIN:
        interventions.append(Intervention(
            type=InterventionType.SCOPING,
            message=(
                "This request contains multiple parts. Consider submitting "
                "each part as a separate task for more focused results."
            ),
            confidence=0.7,
            source="scoping:conjunctions",
        ))

    # Check for numbered list patterns
    numbered_items = re.findall(r"(?:^|\s)(\d+)[.)]\s", ctx.query)
    if len(numbered_items) >= 3:
        interventions.append(Intervention(
            type=InterventionType.SCOPING,
            message=(
                f"Your request lists {len(numbered_items)} items. "
                "Each could be its own task for deeper analysis."
            ),
            confidence=0.8,
            source="scoping:numbered_list",
        ))

    # Check for sequential markers
    sequential_markers = ["first", "second", "third", "then", "finally", "lastly"]
    marker_count = sum(1 for m in sequential_markers if m in query_lower)
    if marker_count >= 3:
        interventions.append(Intervention(
            type=InterventionType.SCOPING,
            message=(
                "This looks like a multi-step process. Consider breaking it "
                "into individual steps for better tracking."
            ),
            confidence=0.6,
            source="scoping:sequential",
        ))

    # Check for multiple question marks
    question_count = ctx.query.count("?")
    if question_count > 1:
        interventions.append(Intervention(
            type=InterventionType.SCOPING,
            message=(
                f"Your request contains {question_count} questions. "
                "Each question may deserve its own focused investigation."
            ),
            confidence=0.6,
            source="scoping:multiple_questions",
        ))

    return interventions


def detect_capability_education(ctx: InterventionContext) -> list[Intervention]:
    """Suggest features the user hasn't tried.

    Triggers:
    - Research intent but used note instrument
    - Comparison language but not using synthesis
    - Image/photo mentions but not using vision
    """
    interventions: list[Intervention] = []
    query_lower = ctx.query.lower()

    # Research intent but used basic note instrument
    if ctx.intent_type == "research" and ctx.instrument_used == "note":
        if "research" in ctx.available_instruments:
            interventions.append(Intervention(
                type=InterventionType.EDUCATION,
                message=(
                    "Tip: The research instrument can perform deeper "
                    "multi-source investigation for research queries."
                ),
                confidence=0.6,
                source="education:research_instrument",
            ))

    # Comparison/decision language but not using synthesis
    comparison_patterns = [
        r"\bcompare\b", r"\bvs\.?\b", r"\bversus\b",
        r"\bpros\s+and\s+cons\b", r"\bwhich\s+is\s+better\b",
        r"\bdifference\s+between\b",
    ]
    has_comparison = any(re.search(p, query_lower) for p in comparison_patterns)
    if has_comparison and ctx.instrument_used != "synthesis":
        if "synthesis" in ctx.available_instruments:
            interventions.append(Intervention(
                type=InterventionType.EDUCATION,
                message=(
                    "Tip: The synthesis instrument excels at comparing "
                    "options and combining perspectives."
                ),
                confidence=0.5,
                source="education:synthesis_instrument",
            ))

    # Image/photo mentions but not using vision
    vision_patterns = [
        r"\bimage\b", r"\bphoto\b", r"\bpicture\b",
        r"\bscreenshot\b", r"\bdiagram\b",
    ]
    has_vision_need = any(re.search(p, query_lower) for p in vision_patterns)
    if has_vision_need and ctx.instrument_used != "vision":
        if "vision" in ctx.available_instruments:
            interventions.append(Intervention(
                type=InterventionType.EDUCATION,
                message=(
                    "Tip: The vision instrument can analyze images "
                    "and visual content directly."
                ),
                confidence=0.5,
                source="education:vision_instrument",
            ))

    return interventions


def _query_similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity between two queries."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
