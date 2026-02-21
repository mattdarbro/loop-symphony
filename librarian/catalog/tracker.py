"""Arrangement tracker - tracks executions and suggests saving (Phase 3C).

Meta-learning component that:
1. Tracks arrangement execution results
2. Identifies high-performing arrangements
3. Suggests saving successful patterns
4. Loads saved arrangements for reuse
"""

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime, UTC
from typing import Any
from uuid import UUID, uuid4

from loop_library.models.arrangement import ArrangementProposal
from loop_library.models.loop_proposal import LoopProposal
from librarian.catalog.models import (
    ArrangementExecution,
    ArrangementStats,
    ArrangementSuggestion,
    SavedArrangement,
    SaveArrangementRequest,
)

logger = logging.getLogger(__name__)

# Thresholds for suggesting to save an arrangement
MIN_EXECUTIONS_FOR_SUGGESTION = 3
MIN_SUCCESS_RATE_FOR_SUGGESTION = 0.7
MIN_CONFIDENCE_FOR_SUGGESTION = 0.75


class ArrangementTracker:
    """Tracks arrangement executions and suggests saving successful ones.

    Maintains in-memory statistics and syncs with database for persistence.
    """

    def __init__(self) -> None:
        # In-memory tracking (keyed by arrangement hash)
        self._executions: dict[str, list[ArrangementExecution]] = defaultdict(list)
        self._arrangements: dict[str, ArrangementProposal | LoopProposal] = {}

        # Saved arrangements (loaded from DB)
        self._saved: dict[str, SavedArrangement] = {}

    def _hash_arrangement(
        self, arrangement: ArrangementProposal | LoopProposal
    ) -> str:
        """Generate a stable hash for an arrangement."""
        if isinstance(arrangement, ArrangementProposal):
            data = {
                "type": "composition",
                "composition_type": arrangement.type,
                "steps": [s.model_dump(mode="json") for s in arrangement.steps] if arrangement.steps else None,
                "branches": arrangement.branches,
                "merge_instrument": arrangement.merge_instrument,
                "instrument": arrangement.instrument,
            }
        else:
            data = {
                "type": "loop",
                "name": arrangement.name,
                "phases": [p.model_dump(mode="json") for p in arrangement.phases],
            }

        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]

    def record_execution(
        self,
        arrangement: ArrangementProposal | LoopProposal,
        task_id: str,
        outcome: str,
        confidence: float,
        duration_ms: int,
    ) -> None:
        """Record an arrangement execution.

        Args:
            arrangement: The arrangement that was executed
            task_id: The task ID
            outcome: Execution outcome (complete, saturated, bounded, inconclusive)
            confidence: Final confidence score
            duration_ms: Execution duration in milliseconds
        """
        arrangement_id = self._hash_arrangement(arrangement)

        execution = ArrangementExecution(
            arrangement_id=arrangement_id,
            task_id=task_id,
            outcome=outcome,
            confidence=confidence,
            duration_ms=duration_ms,
        )

        self._executions[arrangement_id].append(execution)
        self._arrangements[arrangement_id] = arrangement

        logger.debug(
            f"Recorded execution for arrangement {arrangement_id}: "
            f"outcome={outcome}, confidence={confidence:.2f}"
        )

    def get_stats(
        self, arrangement: ArrangementProposal | LoopProposal
    ) -> ArrangementStats:
        """Get aggregated statistics for an arrangement.

        Args:
            arrangement: The arrangement to get stats for

        Returns:
            ArrangementStats with execution metrics
        """
        arrangement_id = self._hash_arrangement(arrangement)
        executions = self._executions.get(arrangement_id, [])

        if not executions:
            return ArrangementStats()

        successful = sum(1 for e in executions if e.outcome == "complete")
        avg_confidence = sum(e.confidence for e in executions) / len(executions)
        avg_duration = sum(e.duration_ms for e in executions) / len(executions)
        last_executed = max(e.executed_at for e in executions)

        return ArrangementStats(
            total_executions=len(executions),
            successful_executions=successful,
            average_confidence=avg_confidence,
            average_duration_ms=avg_duration,
            last_executed_at=last_executed,
        )

    def should_suggest_saving(
        self, arrangement: ArrangementProposal | LoopProposal
    ) -> bool:
        """Check if an arrangement should be suggested for saving.

        Args:
            arrangement: The arrangement to check

        Returns:
            True if the arrangement meets the threshold for suggestion
        """
        stats = self.get_stats(arrangement)

        # Check thresholds
        if stats.total_executions < MIN_EXECUTIONS_FOR_SUGGESTION:
            return False
        if stats.success_rate < MIN_SUCCESS_RATE_FOR_SUGGESTION:
            return False
        if stats.average_confidence < MIN_CONFIDENCE_FOR_SUGGESTION:
            return False

        # Check if already saved
        arrangement_id = self._hash_arrangement(arrangement)
        if arrangement_id in self._saved:
            return False

        return True

    def get_suggestion(
        self, arrangement: ArrangementProposal | LoopProposal
    ) -> ArrangementSuggestion | None:
        """Get a suggestion to save an arrangement if warranted.

        Args:
            arrangement: The arrangement to potentially suggest

        Returns:
            ArrangementSuggestion if the arrangement should be saved, None otherwise
        """
        if not self.should_suggest_saving(arrangement):
            return None

        stats = self.get_stats(arrangement)

        # Generate suggested metadata
        if isinstance(arrangement, ArrangementProposal):
            suggested_name = f"learned_{arrangement.type}"
            if arrangement.type == "sequential" and arrangement.steps:
                instruments = [s.instrument for s in arrangement.steps]
                suggested_name = "_then_".join(instruments)
            elif arrangement.type == "parallel" and arrangement.branches:
                suggested_name = f"parallel_{'_'.join(arrangement.branches)}"

            suggested_description = arrangement.rationale
            arrangement_type = "composition"
        else:
            suggested_name = arrangement.name
            suggested_description = arrangement.description
            arrangement_type = "loop"

        return ArrangementSuggestion(
            arrangement_type=arrangement_type,
            composition_spec=arrangement if isinstance(arrangement, ArrangementProposal) else None,
            loop_spec=arrangement if isinstance(arrangement, LoopProposal) else None,
            reason=f"This arrangement has performed well over {stats.total_executions} executions",
            confidence=stats.average_confidence,
            success_rate=stats.success_rate,
            execution_count=stats.total_executions,
            suggested_name=suggested_name,
            suggested_description=suggested_description,
            suggested_patterns=[],  # Could be inferred from query patterns
        )

    def save_arrangement(
        self,
        request: SaveArrangementRequest,
        app_id: UUID | None = None,
    ) -> SavedArrangement:
        """Save an arrangement for future reuse.

        Args:
            request: The save request with arrangement and metadata
            app_id: Optional app ID for app-specific arrangements

        Returns:
            The saved arrangement

        Raises:
            ValueError: If the arrangement name already exists
        """
        # Check for duplicate name
        for saved in self._saved.values():
            if saved.name == request.name and saved.app_id == app_id:
                raise ValueError(f"Arrangement '{request.name}' already exists")

        # Determine arrangement type
        if request.composition_spec:
            arrangement_type = "composition"
            arrangement = request.composition_spec
        elif request.loop_spec:
            arrangement_type = "loop"
            arrangement = request.loop_spec
        else:
            raise ValueError("Either composition_spec or loop_spec must be provided")

        arrangement_id = self._hash_arrangement(arrangement)
        stats = self.get_stats(arrangement)

        saved = SavedArrangement(
            id=uuid4(),
            app_id=app_id,
            name=request.name,
            description=request.description,
            arrangement_type=arrangement_type,
            composition_spec=request.composition_spec,
            loop_spec=request.loop_spec,
            query_patterns=request.query_patterns,
            tags=request.tags,
            stats=stats,
        )

        self._saved[str(saved.id)] = saved

        logger.info(
            f"Saved arrangement '{request.name}' (id={saved.id}, "
            f"type={arrangement_type})"
        )

        return saved

    def get_saved_arrangements(
        self, app_id: UUID | None = None
    ) -> list[SavedArrangement]:
        """Get all saved arrangements.

        Args:
            app_id: Optional app ID to filter by

        Returns:
            List of saved arrangements
        """
        arrangements = list(self._saved.values())

        if app_id is not None:
            # Include global (app_id=None) and app-specific
            arrangements = [
                a for a in arrangements
                if a.app_id is None or a.app_id == app_id
            ]

        return [a for a in arrangements if a.is_active]

    def get_saved_arrangement(self, arrangement_id: str) -> SavedArrangement | None:
        """Get a saved arrangement by ID.

        Args:
            arrangement_id: The arrangement ID

        Returns:
            The saved arrangement or None
        """
        return self._saved.get(arrangement_id)

    def get_saved_arrangement_by_name(
        self, name: str, app_id: UUID | None = None
    ) -> SavedArrangement | None:
        """Get a saved arrangement by name.

        Args:
            name: The arrangement name
            app_id: Optional app ID

        Returns:
            The saved arrangement or None
        """
        for saved in self._saved.values():
            if saved.name == name:
                if app_id is None or saved.app_id is None or saved.app_id == app_id:
                    return saved
        return None

    def delete_arrangement(self, arrangement_id: str) -> bool:
        """Delete a saved arrangement.

        Args:
            arrangement_id: The arrangement ID

        Returns:
            True if deleted, False if not found
        """
        if arrangement_id in self._saved:
            del self._saved[arrangement_id]
            logger.info(f"Deleted arrangement {arrangement_id}")
            return True
        return False

    def find_matching_arrangement(
        self, query: str, app_id: UUID | None = None
    ) -> SavedArrangement | None:
        """Find a saved arrangement that matches a query.

        Uses simple pattern matching against saved query_patterns.

        Args:
            query: The user's query
            app_id: Optional app ID

        Returns:
            Best matching saved arrangement or None
        """
        query_lower = query.lower()
        best_match: SavedArrangement | None = None
        best_score = 0

        for saved in self.get_saved_arrangements(app_id):
            for pattern in saved.query_patterns:
                pattern_lower = pattern.lower()
                if pattern_lower in query_lower:
                    # Simple scoring: longer patterns are more specific
                    score = len(pattern)
                    if score > best_score:
                        best_score = score
                        best_match = saved

        return best_match

    def load_from_db(self, arrangements: list[dict]) -> None:
        """Load saved arrangements from database.

        Args:
            arrangements: List of arrangement dicts from database
        """
        for data in arrangements:
            try:
                saved = SavedArrangement(**data)
                self._saved[str(saved.id)] = saved
            except Exception as e:
                logger.error(f"Failed to load arrangement: {e}")

        logger.info(f"Loaded {len(self._saved)} saved arrangements from database")

    def export_for_db(self) -> list[dict]:
        """Export saved arrangements for database storage.

        Returns:
            List of arrangement dicts for database
        """
        return [
            saved.model_dump(mode="json")
            for saved in self._saved.values()
        ]
