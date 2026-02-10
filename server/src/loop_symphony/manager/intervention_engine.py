"""Intervention engine — post-task enrichment orchestrator (Phase 5C).

Runs detector functions against completed task responses,
applies trust-level gating, and injects suggestions into
the response's suggested_followups field.

Design: fail-open — errors never block task completion.
"""

import logging

from loop_symphony.manager.error_tracker import ErrorTracker
from loop_symphony.manager.intervention_detectors import (
    detect_capability_education,
    detect_proactive_suggestions,
    detect_pushback,
    detect_scoping,
)
from loop_symphony.manager.trust_tracker import TrustTracker
from loop_symphony.models.intervention import (
    Intervention,
    InterventionContext,
    InterventionResult,
    InterventionType,
)
from loop_symphony.models.task import TaskRequest, TaskResponse

logger = logging.getLogger(__name__)

MAX_INTERVENTIONS = 3
MAX_RECENT_QUERIES = 20

# Trust gating: which intervention types are allowed at each trust level
TRUST_GATE: dict[int, set[InterventionType]] = {
    0: {
        InterventionType.PROACTIVE,
        InterventionType.PUSHBACK,
        InterventionType.SCOPING,
        InterventionType.EDUCATION,
    },
    1: {
        InterventionType.PROACTIVE,
        InterventionType.PUSHBACK,
        InterventionType.SCOPING,
    },
    2: {
        InterventionType.PROACTIVE,
        InterventionType.PUSHBACK,
    },
}

# All detector functions
_DETECTORS = [
    detect_proactive_suggestions,
    detect_pushback,
    detect_scoping,
    detect_capability_education,
]


class InterventionEngine:
    """Orchestrates post-task intervention detection.

    Pipeline:
    1. Build context from request + response + tracker state
    2. Run all detector functions
    3. Apply trust-level gating
    4. Sort by confidence, cap at MAX_INTERVENTIONS
    5. Inject into response.suggested_followups
    """

    def __init__(
        self,
        error_tracker: ErrorTracker,
        trust_tracker: TrustTracker,
    ) -> None:
        self._error_tracker = error_tracker
        self._trust_tracker = trust_tracker
        self._recent_queries: list[str] = []
        self._available_instruments: list[str] = [
            "note", "research", "synthesis", "vision",
        ]

    def build_context(
        self, request: TaskRequest, response: TaskResponse
    ) -> InterventionContext:
        """Assemble context from request, response, and tracker state."""
        trust_level = 0
        if request.preferences:
            trust_level = request.preferences.trust_level

        # Get error patterns (fail-safe)
        error_patterns: list[dict] = []
        try:
            patterns = self._error_tracker.get_patterns()
            error_patterns = [
                {
                    "category": p.category.value,
                    "occurrence_count": p.occurrence_count,
                    "suggested_action": p.suggested_action,
                }
                for p in patterns
            ]
        except Exception:
            pass

        # Extract intent type
        intent_type: str | None = None
        if request.context and request.context.intent:
            intent_type = request.context.intent.type.value

        return InterventionContext(
            query=request.query,
            response_summary=response.summary,
            response_outcome=response.outcome.value,
            response_confidence=response.confidence,
            instrument_used=response.metadata.instrument_used,
            intent_type=intent_type,
            trust_level=trust_level,
            error_patterns=error_patterns,
            recent_queries=list(self._recent_queries),
            available_instruments=list(self._available_instruments),
            suggested_followups=list(response.suggested_followups),
        )

    def evaluate(self, ctx: InterventionContext) -> InterventionResult:
        """Run all detectors, apply trust gating, cap results."""
        allowed_types = TRUST_GATE.get(ctx.trust_level, TRUST_GATE[2])

        all_interventions: list[Intervention] = []
        for detector in _DETECTORS:
            try:
                found = detector(ctx)
                all_interventions.extend(found)
            except Exception as e:
                logger.warning(f"Detector {detector.__name__} failed: {e}")

        # Filter by trust gate
        gated = [i for i in all_interventions if i.type in allowed_types]

        # Sort by confidence descending, cap at MAX
        gated.sort(key=lambda i: i.confidence, reverse=True)

        return InterventionResult(
            interventions=gated[:MAX_INTERVENTIONS],
            context_used=ctx,
        )

    def evaluate_task(
        self, request: TaskRequest, response: TaskResponse
    ) -> InterventionResult:
        """Full pipeline: track query, build context, evaluate."""
        # Track query for recurring pattern detection
        self._recent_queries.append(request.query)
        if len(self._recent_queries) > MAX_RECENT_QUERIES:
            self._recent_queries = self._recent_queries[-MAX_RECENT_QUERIES:]

        ctx = self.build_context(request, response)
        return self.evaluate(ctx)

    @staticmethod
    def enrich_response(
        response: TaskResponse, result: InterventionResult
    ) -> TaskResponse:
        """Inject interventions into response's suggested_followups."""
        for intervention in result.interventions:
            prefixed = f"[{intervention.type.value}] {intervention.message}"
            response.suggested_followups.append(prefixed)
        return response

    def get_status(self) -> dict:
        """Return engine status for the status endpoint."""
        return {
            "recent_queries_count": len(self._recent_queries),
            "available_instruments": self._available_instruments,
            "max_interventions": MAX_INTERVENTIONS,
        }
