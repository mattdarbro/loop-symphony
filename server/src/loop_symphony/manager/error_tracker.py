"""Error tracking and pattern learning (Phase 3H).

Records errors with context, detects patterns over time, and provides
suggestions to avoid repeating mistakes.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, UTC
from uuid import UUID

from loop_symphony.models.error_learning import (
    ErrorCategory,
    ErrorPattern,
    ErrorRecord,
    ErrorSeverity,
    ErrorStats,
    LearningInsight,
)

logger = logging.getLogger(__name__)


# Minimum occurrences before we consider something a pattern
PATTERN_THRESHOLD = 3

# How recent errors need to be to count toward patterns (hours)
PATTERN_WINDOW_HOURS = 168  # 1 week


class ErrorTracker:
    """Tracks errors and learns patterns for institutional knowledge.

    Provides:
    - Error recording with rich context
    - Pattern detection across error history
    - Suggestions based on learned patterns
    - Statistics for monitoring
    """

    def __init__(self) -> None:
        """Initialize the error tracker."""
        self._errors: list[ErrorRecord] = []
        self._patterns: dict[UUID, ErrorPattern] = {}

        # Index for faster lookups
        self._by_category: dict[ErrorCategory, list[ErrorRecord]] = defaultdict(list)
        self._by_instrument: dict[str, list[ErrorRecord]] = defaultdict(list)
        self._by_tool: dict[str, list[ErrorRecord]] = defaultdict(list)

    def record_error(
        self,
        category: ErrorCategory,
        error_message: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        task_id: str | None = None,
        query: str | None = None,
        instrument: str | None = None,
        tool: str | None = None,
        error_type: str | None = None,
        stack_trace: str | None = None,
        query_intent: str | None = None,
        iteration: int | None = None,
        findings_count: int | None = None,
        was_recovered: bool = False,
        recovery_method: str | None = None,
    ) -> ErrorRecord:
        """Record an error with learning context.

        Args:
            category: Classification of the error
            error_message: The error message
            severity: How severe the error was
            task_id: Associated task ID
            query: The query that caused the error
            instrument: Which instrument was running
            tool: Which tool failed (if applicable)
            error_type: Exception class name
            stack_trace: Full stack trace
            query_intent: The inferred intent type
            iteration: Which iteration the error occurred on
            findings_count: How many findings existed before failure
            was_recovered: Whether we recovered from the error
            recovery_method: How we recovered

        Returns:
            The recorded ErrorRecord
        """
        record = ErrorRecord(
            category=category,
            severity=severity,
            error_message=error_message,
            task_id=task_id,
            query=query,
            instrument=instrument,
            tool=tool,
            error_type=error_type,
            stack_trace=stack_trace,
            query_intent=query_intent,
            iteration=iteration,
            findings_count=findings_count,
            was_recovered=was_recovered,
            recovery_method=recovery_method,
        )

        self._errors.append(record)
        self._by_category[category].append(record)
        if instrument:
            self._by_instrument[instrument].append(record)
        if tool:
            self._by_tool[tool].append(record)

        logger.info(
            f"Recorded error: {category.value} - {error_message[:100]}"
            f" (instrument={instrument}, tool={tool})"
        )

        # Check if this creates or updates a pattern
        self._check_for_patterns(record)

        return record

    def _check_for_patterns(self, new_error: ErrorRecord) -> None:
        """Check if the new error creates or updates a pattern."""
        cutoff = datetime.now(UTC) - timedelta(hours=PATTERN_WINDOW_HOURS)
        recent_same_category = [
            e for e in self._by_category[new_error.category]
            if e.timestamp >= cutoff
        ]

        # Check for instrument-specific patterns
        if new_error.instrument:
            instrument_errors = [
                e for e in recent_same_category
                if e.instrument == new_error.instrument
            ]
            if len(instrument_errors) >= PATTERN_THRESHOLD:
                self._create_or_update_pattern(
                    name=f"{new_error.instrument}_{new_error.category.value}",
                    description=f"{new_error.instrument} frequently fails with {new_error.category.value}",
                    category=new_error.category,
                    instrument=new_error.instrument,
                    count=len(instrument_errors),
                )

        # Check for tool-specific patterns
        if new_error.tool:
            tool_errors = [
                e for e in recent_same_category
                if e.tool == new_error.tool
            ]
            if len(tool_errors) >= PATTERN_THRESHOLD:
                self._create_or_update_pattern(
                    name=f"{new_error.tool}_{new_error.category.value}",
                    description=f"{new_error.tool} frequently fails with {new_error.category.value}",
                    category=new_error.category,
                    tool=new_error.tool,
                    count=len(tool_errors),
                )

        # Check for query keyword patterns
        if new_error.query:
            self._check_query_patterns(new_error, recent_same_category)

    def _check_query_patterns(
        self,
        new_error: ErrorRecord,
        similar_errors: list[ErrorRecord],
    ) -> None:
        """Look for patterns in query text that correlate with errors."""
        if not new_error.query:
            return

        # Extract keywords from failing queries
        queries_with_errors = [e.query for e in similar_errors if e.query]
        if len(queries_with_errors) < PATTERN_THRESHOLD:
            return

        # Simple keyword extraction - find common words
        word_counts: dict[str, int] = defaultdict(int)
        for query in queries_with_errors:
            words = set(query.lower().split())
            for word in words:
                if len(word) > 3:  # Skip short words
                    word_counts[word] += 1

        # Find words that appear in most failing queries
        threshold = len(queries_with_errors) * 0.6
        common_keywords = [
            word for word, count in word_counts.items()
            if count >= threshold
        ]

        if common_keywords:
            pattern_name = f"query_{common_keywords[0]}_{new_error.category.value}"
            self._create_or_update_pattern(
                name=pattern_name,
                description=f"Queries containing '{common_keywords[0]}' often fail with {new_error.category.value}",
                category=new_error.category,
                query_pattern=common_keywords[0],
                count=len(similar_errors),
            )

    def _create_or_update_pattern(
        self,
        name: str,
        description: str,
        category: ErrorCategory,
        instrument: str | None = None,
        tool: str | None = None,
        query_pattern: str | None = None,
        count: int = 1,
    ) -> ErrorPattern:
        """Create a new pattern or update existing one."""
        # Check if pattern already exists
        existing = None
        for pattern in self._patterns.values():
            if pattern.name == name:
                existing = pattern
                break

        if existing:
            existing.occurrence_count = count
            existing.last_seen = datetime.now(UTC)
            existing.updated_at = datetime.now(UTC)
            # Increase confidence as pattern persists
            existing.confidence = min(0.95, existing.confidence + 0.05)
            logger.debug(f"Updated pattern: {name} (count={count})")
            return existing

        # Create new pattern
        pattern = ErrorPattern(
            name=name,
            description=description,
            category=category,
            instrument=instrument,
            tool=tool,
            query_pattern=query_pattern,
            occurrence_count=count,
            suggested_action=self._suggest_action(category, instrument, tool),
        )
        self._patterns[pattern.id] = pattern
        logger.info(f"Detected new pattern: {name}")
        return pattern

    def _suggest_action(
        self,
        category: ErrorCategory,
        instrument: str | None,
        tool: str | None,
    ) -> str:
        """Generate a suggested action for a pattern."""
        suggestions = {
            ErrorCategory.TIMEOUT: "Consider reducing query complexity or increasing timeout",
            ErrorCategory.RATE_LIMITED: "Add delays between requests or use caching",
            ErrorCategory.LOW_CONFIDENCE: "Try a more specific query or different instrument",
            ErrorCategory.CONTRADICTIONS: "Use fact-checking instrument or break into sub-queries",
            ErrorCategory.NO_RESULTS: "Broaden search terms or try alternative sources",
            ErrorCategory.DEPTH_EXCEEDED: "Simplify the task or increase depth limit",
            ErrorCategory.CONTEXT_OVERFLOW: "Use compaction strategies to reduce context size",
            ErrorCategory.API_FAILURE: "Check API status, consider fallback tool",
            ErrorCategory.INSTRUMENT_FAILURE: "Try alternative instrument for this query type",
            ErrorCategory.ARRANGEMENT_FAILURE: "Simplify composition or use sequential instead of parallel",
            ErrorCategory.TOOL_FAILURE: "Check tool health, consider alternative",
        }

        base_suggestion = suggestions.get(
            category,
            "Review error details and adjust approach"
        )

        if instrument:
            return f"{base_suggestion}. Consider alternatives to {instrument}."
        if tool:
            return f"{base_suggestion}. {tool} may need attention."

        return base_suggestion

    def get_suggestions(
        self,
        query: str | None = None,
        instrument: str | None = None,
        tool: str | None = None,
    ) -> list[LearningInsight]:
        """Get suggestions based on learned patterns.

        Args:
            query: The query about to be executed
            instrument: The instrument to be used
            tool: The tool to be used

        Returns:
            List of relevant suggestions
        """
        insights: list[LearningInsight] = []

        for pattern in self._patterns.values():
            relevance = self._pattern_relevance(pattern, query, instrument, tool)
            if relevance > 0.3:
                insights.append(LearningInsight(
                    pattern_id=pattern.id,
                    pattern_name=pattern.name,
                    suggestion=pattern.suggested_action or "Review past errors for this pattern",
                    confidence=pattern.confidence * relevance,
                    reason=pattern.description,
                ))

        # Sort by confidence
        insights.sort(key=lambda x: x.confidence, reverse=True)
        return insights[:5]  # Top 5 most relevant

    def _pattern_relevance(
        self,
        pattern: ErrorPattern,
        query: str | None,
        instrument: str | None,
        tool: str | None,
    ) -> float:
        """Calculate how relevant a pattern is to the current context."""
        score = 0.0
        matches = 0

        if pattern.instrument and instrument:
            matches += 1
            if pattern.instrument == instrument:
                score += 1.0

        if pattern.tool and tool:
            matches += 1
            if pattern.tool == tool:
                score += 1.0

        if pattern.query_pattern and query:
            matches += 1
            if pattern.query_pattern.lower() in query.lower():
                score += 1.0

        if matches == 0:
            return 0.0

        return score / matches

    def get_stats(self) -> ErrorStats:
        """Get aggregate error statistics."""
        now = datetime.now(UTC)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(hours=24)

        by_category: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        by_instrument: dict[str, int] = defaultdict(int)
        recovered = 0
        errors_last_hour = 0
        errors_last_24h = 0

        for error in self._errors:
            by_category[error.category.value] += 1
            by_severity[error.severity.value] += 1
            if error.instrument:
                by_instrument[error.instrument] += 1
            if error.was_recovered:
                recovered += 1
            if error.timestamp >= hour_ago:
                errors_last_hour += 1
            if error.timestamp >= day_ago:
                errors_last_24h += 1

        total = len(self._errors)
        return ErrorStats(
            total_errors=total,
            errors_by_category=dict(by_category),
            errors_by_severity=dict(by_severity),
            errors_by_instrument=dict(by_instrument),
            recovery_rate=recovered / total if total > 0 else 0.0,
            patterns_detected=len(self._patterns),
            errors_last_hour=errors_last_hour,
            errors_last_24h=errors_last_24h,
        )

    def get_patterns(self) -> list[ErrorPattern]:
        """Get all detected patterns."""
        return list(self._patterns.values())

    def get_pattern(self, pattern_id: UUID) -> ErrorPattern | None:
        """Get a specific pattern by ID."""
        return self._patterns.get(pattern_id)

    def get_recent_errors(
        self,
        limit: int = 20,
        category: ErrorCategory | None = None,
        instrument: str | None = None,
    ) -> list[ErrorRecord]:
        """Get recent errors, optionally filtered."""
        errors = self._errors

        if category:
            errors = self._by_category.get(category, [])
        elif instrument:
            errors = self._by_instrument.get(instrument, [])

        # Sort by timestamp descending
        sorted_errors = sorted(errors, key=lambda e: e.timestamp, reverse=True)
        return sorted_errors[:limit]

    def mark_pattern_success(self, pattern_id: UUID) -> bool:
        """Mark that following a pattern's suggestion led to success.

        This increases confidence in the pattern.
        """
        pattern = self._patterns.get(pattern_id)
        if not pattern:
            return False

        pattern.success_after_adjustment += 1
        pattern.confidence = min(0.99, pattern.confidence + 0.1)
        pattern.updated_at = datetime.now(UTC)
        return True

    def clear_old_errors(self, max_age_hours: int = 720) -> int:
        """Clear errors older than max_age_hours (default 30 days)."""
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        old_count = len(self._errors)

        self._errors = [e for e in self._errors if e.timestamp >= cutoff]

        # Rebuild indexes
        self._by_category = defaultdict(list)
        self._by_instrument = defaultdict(list)
        self._by_tool = defaultdict(list)

        for error in self._errors:
            self._by_category[error.category].append(error)
            if error.instrument:
                self._by_instrument[error.instrument].append(error)
            if error.tool:
                self._by_tool[error.tool].append(error)

        cleaned = old_count - len(self._errors)
        if cleaned > 0:
            logger.info(f"Cleared {cleaned} old error records")
        return cleaned


def classify_exception(exc: Exception) -> tuple[ErrorCategory, ErrorSeverity]:
    """Classify an exception into category and severity.

    Helper function for common exception types.
    """
    exc_name = type(exc).__name__.lower()
    exc_msg = str(exc).lower()

    # Timeout errors
    if "timeout" in exc_name or "timeout" in exc_msg:
        return ErrorCategory.TIMEOUT, ErrorSeverity.MEDIUM

    # Rate limiting
    if "rate" in exc_msg and "limit" in exc_msg:
        return ErrorCategory.RATE_LIMITED, ErrorSeverity.MEDIUM
    if "429" in exc_msg or "too many requests" in exc_msg:
        return ErrorCategory.RATE_LIMITED, ErrorSeverity.MEDIUM

    # API errors
    if "api" in exc_name or "http" in exc_name:
        return ErrorCategory.API_FAILURE, ErrorSeverity.HIGH
    if any(code in exc_msg for code in ["500", "502", "503", "504"]):
        return ErrorCategory.API_FAILURE, ErrorSeverity.HIGH

    # Validation
    if "validation" in exc_name or "invalid" in exc_msg:
        return ErrorCategory.VALIDATION, ErrorSeverity.LOW

    # Depth exceeded
    if "depth" in exc_msg and "exceed" in exc_msg:
        return ErrorCategory.DEPTH_EXCEEDED, ErrorSeverity.MEDIUM

    # Default
    return ErrorCategory.UNKNOWN, ErrorSeverity.MEDIUM
