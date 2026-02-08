"""Knowledge manager (Phase 5A).

Aggregates data from trackers into structured knowledge entries,
renders them as markdown, and provides CRUD operations.
"""

import logging
from datetime import datetime, UTC
from typing import TYPE_CHECKING
from uuid import uuid4

from loop_symphony.models.knowledge import (
    CATEGORY_TITLES,
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeEntryCreate,
    KnowledgeFile,
    KnowledgeRefreshResult,
    KnowledgeSource,
    UserKnowledge,
)

if TYPE_CHECKING:
    from loop_symphony.db.client import DatabaseClient
    from loop_symphony.manager.arrangement_tracker import ArrangementTracker
    from loop_symphony.manager.error_tracker import ErrorTracker
    from loop_symphony.manager.trust_tracker import TrustTracker

logger = logging.getLogger(__name__)


class KnowledgeManager:
    """Manages the knowledge layer.

    Aggregates data from in-memory trackers (errors, arrangements, trust)
    into persistent knowledge entries. Renders entries as markdown for
    the five knowledge files.
    """

    def __init__(
        self,
        db: "DatabaseClient",
        error_tracker: "ErrorTracker | None" = None,
        arrangement_tracker: "ArrangementTracker | None" = None,
        trust_tracker: "TrustTracker | None" = None,
    ) -> None:
        self.db = db
        self.error_tracker = error_tracker
        self.arrangement_tracker = arrangement_tracker
        self.trust_tracker = trust_tracker

    async def get_file(
        self,
        category: KnowledgeCategory,
        user_id: str | None = None,
    ) -> KnowledgeFile:
        """Load a knowledge file by category.

        Args:
            category: The knowledge category
            user_id: For USER category, the user ID

        Returns:
            Rendered KnowledgeFile with markdown and entries
        """
        if category == KnowledgeCategory.USER and user_id is None:
            return KnowledgeFile(
                category=category,
                title=CATEGORY_TITLES[category],
                markdown="No user ID specified.",
                entries=[],
                last_updated=None,
            )

        kwargs: dict = {"category": category.value}
        if user_id is not None:
            kwargs["user_id"] = user_id

        rows = await self.db.list_knowledge_entries(**kwargs)
        entries = [self._row_to_entry(row) for row in rows]

        last_updated = None
        if entries:
            last_updated = max(e.updated_at for e in entries)

        markdown = self._render_markdown(category, entries)

        return KnowledgeFile(
            category=category,
            title=CATEGORY_TITLES[category],
            markdown=markdown,
            entries=entries,
            last_updated=last_updated,
        )

    async def get_user_knowledge(self, user_id: str) -> UserKnowledge:
        """Get aggregated knowledge for a specific user.

        Args:
            user_id: The user ID

        Returns:
            UserKnowledge with trust data and entries
        """
        rows = await self.db.list_knowledge_entries(
            category=KnowledgeCategory.USER.value,
            user_id=user_id,
        )
        entries = [self._row_to_entry(row) for row in rows]

        # Get trust data if tracker available
        trust_level = 0
        total_tasks = 0
        success_rate = 0.0
        preferred_patterns: list[str] = []

        if self.trust_tracker:
            # Look through all metrics for this user_id
            for (app_id, uid), metrics in self.trust_tracker._metrics.items():
                if uid is not None and str(uid) == user_id:
                    trust_level = metrics.current_trust_level
                    total_tasks = metrics.total_tasks
                    success_rate = metrics.success_rate
                    break

        # Extract patterns from entries
        for entry in entries:
            if "pattern" in entry.title.lower() or "preference" in entry.title.lower():
                preferred_patterns.append(entry.title)

        markdown = self._render_user_markdown(
            user_id, entries, trust_level, total_tasks, success_rate
        )

        return UserKnowledge(
            user_id=user_id,
            trust_level=trust_level,
            total_tasks=total_tasks,
            success_rate=success_rate,
            preferred_patterns=preferred_patterns,
            entries=entries,
            markdown=markdown,
        )

    async def add_entry(
        self, create: KnowledgeEntryCreate
    ) -> KnowledgeEntry:
        """Create a manual knowledge entry.

        Args:
            create: The entry creation request

        Returns:
            The created entry
        """
        entry_data = {
            "category": create.category.value,
            "title": create.title,
            "content": create.content,
            "source": KnowledgeSource.MANUAL.value,
            "confidence": create.confidence,
            "user_id": create.user_id,
            "tags": create.tags,
        }
        row = await self.db.create_knowledge_entry(entry_data)
        return self._row_to_entry(row)

    async def list_entries(
        self,
        category: str | None = None,
        source: str | None = None,
    ) -> list[KnowledgeEntry]:
        """List knowledge entries with optional filters.

        Args:
            category: Filter by category value
            source: Filter by source value

        Returns:
            List of entries
        """
        rows = await self.db.list_knowledge_entries(
            category=category, source=source
        )
        return [self._row_to_entry(row) for row in rows]

    async def refresh_from_trackers(self) -> KnowledgeRefreshResult:
        """Refresh knowledge entries from in-memory trackers.

        Clears old tracker-derived entries and creates new ones from
        current tracker state.

        Returns:
            Summary of what was created/removed
        """
        entries_created = 0
        entries_removed = 0
        sources_refreshed: list[str] = []

        if self.error_tracker:
            new_entries = self._extract_error_patterns()
            removed = await self._replace_source_entries(
                KnowledgeSource.ERROR_TRACKER, new_entries
            )
            entries_created += len(new_entries)
            entries_removed += removed
            sources_refreshed.append(KnowledgeSource.ERROR_TRACKER.value)

        if self.arrangement_tracker:
            new_entries = self._extract_arrangement_patterns()
            removed = await self._replace_source_entries(
                KnowledgeSource.ARRANGEMENT_TRACKER, new_entries
            )
            entries_created += len(new_entries)
            entries_removed += removed
            sources_refreshed.append(KnowledgeSource.ARRANGEMENT_TRACKER.value)

        if self.trust_tracker:
            new_entries = self._extract_trust_patterns()
            removed = await self._replace_source_entries(
                KnowledgeSource.TRUST_TRACKER, new_entries
            )
            entries_created += len(new_entries)
            entries_removed += removed
            sources_refreshed.append(KnowledgeSource.TRUST_TRACKER.value)

        logger.info(
            f"Knowledge refresh: {entries_created} created, "
            f"{entries_removed} removed from {sources_refreshed}"
        )

        return KnowledgeRefreshResult(
            entries_created=entries_created,
            entries_removed=entries_removed,
            sources_refreshed=sources_refreshed,
        )

    # -------------------------------------------------------------------------
    # Private: tracker extraction
    # -------------------------------------------------------------------------

    def _extract_error_patterns(self) -> list[dict]:
        """Extract knowledge entries from error tracker patterns."""
        if not self.error_tracker:
            return []

        entries: list[dict] = []
        patterns = self.error_tracker.get_patterns()

        for pattern in patterns:
            # High-occurrence patterns become boundary knowledge
            if pattern.occurrence_count >= 5:
                entries.append({
                    "category": KnowledgeCategory.BOUNDARIES.value,
                    "title": f"Known limitation: {pattern.name}",
                    "content": (
                        f"{pattern.description}. "
                        f"Occurred {pattern.occurrence_count} times. "
                        f"{pattern.suggested_action or 'No suggested workaround yet.'}"
                    ),
                    "confidence": min(pattern.confidence, 1.0),
                    "tags": ["error-pattern", "learned"],
                })

            # All patterns go to patterns knowledge
            entries.append({
                "category": KnowledgeCategory.PATTERNS.value,
                "title": f"Error pattern: {pattern.name}",
                "content": (
                    f"{pattern.description}. "
                    f"Seen {pattern.occurrence_count} times "
                    f"(confidence: {pattern.confidence:.0%}). "
                    f"{pattern.suggested_action or ''}"
                ),
                "confidence": min(pattern.confidence, 1.0),
                "tags": ["error-pattern", "learned"],
            })

        # Add stats summary if there are errors
        stats = self.error_tracker.get_stats()
        if stats.total_errors > 0:
            entries.append({
                "category": KnowledgeCategory.PATTERNS.value,
                "title": "Error statistics summary",
                "content": (
                    f"Total errors tracked: {stats.total_errors}. "
                    f"Recovery rate: {stats.recovery_rate:.0%}. "
                    f"Most common category: "
                    f"{max(stats.by_category.items(), key=lambda x: x[1])[0] if stats.by_category else 'none'}."
                ),
                "confidence": 0.9,
                "tags": ["statistics", "errors"],
            })

        return entries

    def _extract_arrangement_patterns(self) -> list[dict]:
        """Extract knowledge entries from arrangement tracker."""
        if not self.arrangement_tracker:
            return []

        entries: list[dict] = []

        for arr_id, executions in self.arrangement_tracker._executions.items():
            if not executions:
                continue

            arrangement = self.arrangement_tracker._arrangements.get(arr_id)
            if not arrangement:
                continue

            total = len(executions)
            successful = sum(1 for e in executions if e.outcome == "complete")
            success_rate = successful / total if total > 0 else 0
            avg_confidence = sum(e.confidence for e in executions) / total

            # Only report on arrangements with enough data
            if total < 2:
                continue

            arr_name = getattr(arrangement, "name", None) or arr_id[:8]

            if success_rate >= 0.7:
                entries.append({
                    "category": KnowledgeCategory.CAPABILITIES.value,
                    "title": f"Proven arrangement: {arr_name}",
                    "content": (
                        f"Arrangement '{arr_name}' has a {success_rate:.0%} success rate "
                        f"across {total} executions (avg confidence: {avg_confidence:.0%})."
                    ),
                    "confidence": min(avg_confidence, 1.0),
                    "tags": ["arrangement", "proven"],
                })

            entries.append({
                "category": KnowledgeCategory.PATTERNS.value,
                "title": f"Arrangement usage: {arr_name}",
                "content": (
                    f"'{arr_name}': {total} executions, "
                    f"{success_rate:.0%} success, "
                    f"{avg_confidence:.0%} avg confidence."
                ),
                "confidence": min(avg_confidence, 1.0),
                "tags": ["arrangement", "statistics"],
            })

        # Report saved arrangements
        for arr_id, saved in self.arrangement_tracker._saved.items():
            entries.append({
                "category": KnowledgeCategory.CAPABILITIES.value,
                "title": f"Saved arrangement: {saved.name}",
                "content": (
                    f"Reusable arrangement '{saved.name}': {saved.description or 'No description'}. "
                    f"Type: {saved.composition_type}."
                ),
                "confidence": 1.0,
                "tags": ["arrangement", "saved"],
            })

        return entries

    def _extract_trust_patterns(self) -> list[dict]:
        """Extract knowledge entries from trust tracker."""
        if not self.trust_tracker:
            return []

        entries: list[dict] = []

        for (app_id, user_id), metrics in self.trust_tracker._metrics.items():
            if user_id is None:
                continue
            if metrics.total_tasks == 0:
                continue

            entries.append({
                "category": KnowledgeCategory.USER.value,
                "title": f"Trust profile",
                "content": (
                    f"Trust level: {metrics.current_trust_level}. "
                    f"Tasks: {metrics.total_tasks} total, "
                    f"{metrics.success_rate:.0%} success rate. "
                    f"Consecutive successes: {metrics.consecutive_successes}."
                ),
                "user_id": str(user_id),
                "confidence": 1.0,
                "tags": ["trust", "profile"],
            })

        return entries

    async def _replace_source_entries(
        self,
        source: KnowledgeSource,
        new_entries: list[dict],
    ) -> int:
        """Replace all entries from a source with new ones.

        Soft-deletes existing entries, then creates new ones.

        Args:
            source: The knowledge source
            new_entries: New entry dicts to create

        Returns:
            Number of old entries removed
        """
        total_removed = 0

        # Find unique categories in new entries
        categories = {e["category"] for e in new_entries}

        # Also clean categories that had entries from this source before
        # (covers case where tracker no longer produces entries for a category)
        for cat in KnowledgeCategory:
            categories.add(cat.value)

        for category in categories:
            removed = await self.db.delete_knowledge_entries_by_source(
                category=category,
                source=source.value,
            )
            total_removed += removed

        # Create new entries
        for entry_data in new_entries:
            entry_data["source"] = source.value
            await self.db.create_knowledge_entry(entry_data)

        return total_removed

    # -------------------------------------------------------------------------
    # Private: rendering
    # -------------------------------------------------------------------------

    def _render_markdown(
        self,
        category: KnowledgeCategory,
        entries: list[KnowledgeEntry],
    ) -> str:
        """Render knowledge entries as markdown.

        Args:
            category: The category for the header
            entries: Entries to render

        Returns:
            Formatted markdown string
        """
        title = CATEGORY_TITLES[category]
        lines = [f"# {title}", ""]

        if not entries:
            lines.append("*No entries yet.*")
            return "\n".join(lines)

        # Group by source for organized output
        by_source: dict[str, list[KnowledgeEntry]] = {}
        for entry in entries:
            source_label = entry.source.value.replace("_", " ").title()
            by_source.setdefault(source_label, []).append(entry)

        for source_label, source_entries in by_source.items():
            lines.append(f"## {source_label}")
            lines.append("")
            for entry in source_entries:
                confidence_marker = ""
                if entry.confidence < 1.0:
                    confidence_marker = f" *(confidence: {entry.confidence:.0%})*"
                lines.append(f"### {entry.title}{confidence_marker}")
                lines.append("")
                lines.append(entry.content)
                lines.append("")

        return "\n".join(lines)

    def _render_user_markdown(
        self,
        user_id: str,
        entries: list[KnowledgeEntry],
        trust_level: int,
        total_tasks: int,
        success_rate: float,
    ) -> str:
        """Render per-user knowledge as markdown.

        Args:
            user_id: The user ID
            entries: User-specific entries
            trust_level: Current trust level
            total_tasks: Total tasks executed
            success_rate: Success rate

        Returns:
            Formatted markdown string
        """
        lines = [
            f"# User Knowledge: {user_id}",
            "",
            "## Trust Profile",
            "",
            f"- **Trust Level:** {trust_level}",
            f"- **Total Tasks:** {total_tasks}",
            f"- **Success Rate:** {success_rate:.0%}",
            "",
        ]

        if entries:
            lines.append("## Learned Patterns")
            lines.append("")
            for entry in entries:
                lines.append(f"### {entry.title}")
                lines.append("")
                lines.append(entry.content)
                lines.append("")
        else:
            lines.append("*No user-specific patterns learned yet.*")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Private: helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: dict) -> KnowledgeEntry:
        """Convert a database row to a KnowledgeEntry."""
        return KnowledgeEntry(
            id=row["id"],
            category=KnowledgeCategory(row["category"]),
            title=row["title"],
            content=row["content"],
            source=KnowledgeSource(row["source"]),
            confidence=row.get("confidence", 1.0),
            user_id=row.get("user_id"),
            tags=row.get("tags", []),
            is_active=row.get("is_active", True),
            created_at=row.get("created_at", datetime.now(UTC)),
            updated_at=row.get("updated_at", datetime.now(UTC)),
        )
