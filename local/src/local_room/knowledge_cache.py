"""In-memory knowledge cache for Local Room (Phase 5B).

Stores knowledge entries synced from the server. Updated via
heartbeat-piggybacked deltas.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CachedKnowledgeEntry(BaseModel):
    """A knowledge entry cached locally."""

    id: str
    category: str
    title: str
    content: str
    source: str
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)
    version: int = 0


class KnowledgeCache:
    """In-memory cache of server knowledge.

    Receives delta pushes from the server (via heartbeat responses)
    and maintains a local copy for use during task execution.
    """

    def __init__(self) -> None:
        self._entries: dict[str, CachedKnowledgeEntry] = {}
        self._server_version: int = 0

    @property
    def server_version(self) -> int:
        """Last known server knowledge version."""
        return self._server_version

    def apply_sync(self, push_data: dict[str, Any]) -> int:
        """Apply a sync push from the server.

        Args:
            push_data: Dict with server_version, entries, removed_ids

        Returns:
            Number of changes applied
        """
        changes = 0

        # Process new/updated entries
        for entry_data in push_data.get("entries", []):
            entry = CachedKnowledgeEntry(
                id=entry_data["id"],
                category=entry_data["category"],
                title=entry_data["title"],
                content=entry_data["content"],
                source=entry_data.get("source", "unknown"),
                confidence=entry_data.get("confidence", 1.0),
                tags=entry_data.get("tags", []),
                version=entry_data.get("version", 0),
            )
            self._entries[entry.id] = entry
            changes += 1

        # Process removals
        for entry_id in push_data.get("removed_ids", []):
            if entry_id in self._entries:
                del self._entries[entry_id]
                changes += 1

        # Update version
        new_version = push_data.get("server_version", self._server_version)
        if new_version > self._server_version:
            self._server_version = new_version

        if changes:
            logger.info(
                f"Applied sync: {changes} changes, "
                f"now at version {self._server_version}"
            )

        return changes

    def get_entries(
        self,
        category: str | None = None,
    ) -> list[CachedKnowledgeEntry]:
        """List cached entries, optionally filtered by category.

        Args:
            category: Filter by category value

        Returns:
            List of cached entries
        """
        entries = list(self._entries.values())
        if category is not None:
            entries = [e for e in entries if e.category == category]
        return entries

    def get_context_summary(
        self,
        categories: list[str] | None = None,
    ) -> str:
        """Render cached knowledge as a context string.

        Useful for injecting into LLM prompts to give context
        about system capabilities and patterns.

        Args:
            categories: Filter to specific categories

        Returns:
            Formatted context string
        """
        entries = list(self._entries.values())
        if categories:
            entries = [e for e in entries if e.category in categories]

        if not entries:
            return "No knowledge entries available."

        # Group by category
        by_category: dict[str, list[CachedKnowledgeEntry]] = {}
        for entry in entries:
            by_category.setdefault(entry.category, []).append(entry)

        lines: list[str] = []
        for category, cat_entries in sorted(by_category.items()):
            lines.append(f"## {category.replace('_', ' ').title()}")
            for entry in cat_entries:
                conf = f" ({entry.confidence:.0%})" if entry.confidence < 1.0 else ""
                lines.append(f"- **{entry.title}**{conf}: {entry.content}")
            lines.append("")

        return "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with entry counts and version info
        """
        by_category: dict[str, int] = {}
        for entry in self._entries.values():
            by_category[entry.category] = by_category.get(entry.category, 0) + 1

        return {
            "total_entries": len(self._entries),
            "server_version": self._server_version,
            "by_category": by_category,
        }
