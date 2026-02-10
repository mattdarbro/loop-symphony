"""Knowledge sync manager (Phase 5B).

Orchestrates bidirectional knowledge sync between server and rooms.
Computes deltas for push, accepts room learnings, and aggregates
cross-room observations into knowledge entries.
"""

import logging
from collections import defaultdict
from datetime import datetime, UTC
from typing import TYPE_CHECKING

from loop_symphony.models.knowledge import KnowledgeCategory, KnowledgeSource
from loop_symphony.models.knowledge_sync import (
    KnowledgeSyncEntry,
    KnowledgeSyncPush,
    KnowledgeSyncState,
    LearningAggregationResult,
    RoomLearningBatch,
)

if TYPE_CHECKING:
    from loop_symphony.db.client import DatabaseClient
    from loop_symphony.manager.knowledge_manager import KnowledgeManager

logger = logging.getLogger(__name__)

# Minimum number of distinct rooms reporting the same learning
# before it gets promoted to an AGGREGATED knowledge entry.
AGGREGATION_THRESHOLD = 3


class KnowledgeSyncManager:
    """Manages knowledge sync between server and rooms.

    Responsibilities:
    - Compute delta pushes for each room based on version tracking
    - Accept and store room learnings
    - Aggregate cross-room learnings into knowledge entries
    """

    def __init__(
        self,
        db: "DatabaseClient",
        knowledge_manager: "KnowledgeManager",
    ) -> None:
        self.db = db
        self.knowledge_manager = knowledge_manager

    async def get_sync_push(self, room_id: str) -> KnowledgeSyncPush:
        """Compute a sync push for a room.

        Returns entries changed since the room's last synced version,
        plus IDs of entries that were deactivated.

        Args:
            room_id: The room requesting sync

        Returns:
            KnowledgeSyncPush with delta entries and removals
        """
        # Get room's last synced version
        state = await self.db.get_room_sync_state(room_id)
        since_version = state["last_synced_version"] if state else 0

        # Get current server version
        server_version = await self.db.get_knowledge_version()

        # If room is up to date, return empty push
        if since_version >= server_version:
            return KnowledgeSyncPush(server_version=server_version)

        # Get delta entries and removals
        raw_entries = await self.db.get_entries_since_version(since_version)
        removed_ids = await self.db.get_removed_since_version(since_version)

        entries = [
            KnowledgeSyncEntry(
                id=str(row["id"]),
                category=row["category"],
                title=row["title"],
                content=row["content"],
                source=row["source"],
                confidence=row.get("confidence", 1.0),
                tags=row.get("tags", []),
                version=row.get("version", 0),
                updated_at=row.get("updated_at", datetime.now(UTC)),
            )
            for row in raw_entries
        ]

        logger.info(
            f"Sync push for {room_id}: {len(entries)} entries, "
            f"{len(removed_ids)} removals (v{since_version}→v{server_version})"
        )

        return KnowledgeSyncPush(
            server_version=server_version,
            entries=entries,
            removed_ids=removed_ids,
        )

    async def record_sync(self, room_id: str, version: int) -> None:
        """Record that a room has synced up to a version.

        Args:
            room_id: The room ID
            version: The version the room is now synced to
        """
        await self.db.update_room_sync_state(room_id, version)
        logger.debug(f"Room {room_id} synced to version {version}")

    async def accept_learnings(self, batch: RoomLearningBatch) -> int:
        """Accept and store a batch of room learnings.

        Args:
            batch: The learning batch from a room

        Returns:
            Number of learnings stored
        """
        if not batch.learnings:
            return 0

        learning_dicts = [
            {
                "room_id": learning.room_id,
                "category": learning.category,
                "title": learning.title,
                "content": learning.content,
                "confidence": learning.confidence,
                "tags": learning.tags,
                "observed_at": learning.observed_at.isoformat(),
            }
            for learning in batch.learnings
        ]

        count = await self.db.create_room_learnings(learning_dicts)
        logger.info(
            f"Accepted {count} learnings from room {batch.room_id}"
        )
        return count

    async def aggregate_learnings(self) -> LearningAggregationResult:
        """Process unprocessed room learnings into knowledge entries.

        Groups learnings by title. If 3+ distinct rooms report the same
        learning, it becomes an AGGREGATED entry (higher confidence).
        Single-room learnings become ROOM_LEARNING entries (lower confidence).

        Returns:
            Summary of aggregation results
        """
        raw_learnings = await self.db.get_unprocessed_learnings(limit=200)
        if not raw_learnings:
            return LearningAggregationResult()

        # Group by title
        by_title: dict[str, list[dict]] = defaultdict(list)
        for learning in raw_learnings:
            by_title[learning["title"]].append(learning)

        entries_created = 0
        entries_updated = 0

        for title, group in by_title.items():
            distinct_rooms = {l["room_id"] for l in group}
            # Use the first learning as representative
            rep = group[0]
            avg_confidence = sum(l.get("confidence", 0.5) for l in group) / len(group)

            if len(distinct_rooms) >= AGGREGATION_THRESHOLD:
                # Multi-room agreement → AGGREGATED (higher confidence)
                source = KnowledgeSource.AGGREGATED
                confidence = min(avg_confidence + 0.2, 1.0)
                content = (
                    f"{rep['content']} "
                    f"(Observed by {len(distinct_rooms)} rooms, "
                    f"{len(group)} total reports.)"
                )
            else:
                # Single/few rooms → ROOM_LEARNING (lower confidence)
                source = KnowledgeSource.ROOM_LEARNING
                confidence = min(avg_confidence, 0.8)
                content = (
                    f"{rep['content']} "
                    f"(Reported by room: {rep['room_id']}.)"
                )

            entry_data = {
                "category": rep["category"],
                "title": title,
                "content": content,
                "source": source.value,
                "confidence": confidence,
                "tags": rep.get("tags", []),
            }
            await self.db.create_knowledge_entry(entry_data)
            entries_created += 1

        # Mark all processed
        ids = [str(l["id"]) for l in raw_learnings]
        await self.db.mark_learnings_processed(ids)

        logger.info(
            f"Aggregated {len(raw_learnings)} learnings → "
            f"{entries_created} entries created"
        )

        return LearningAggregationResult(
            entries_created=entries_created,
            entries_updated=entries_updated,
            learnings_processed=len(raw_learnings),
        )

    async def get_sync_status(self) -> dict:
        """Get sync status for all rooms.

        Returns:
            Dict with global version and per-room states
        """
        server_version = await self.db.get_knowledge_version()

        # Get all room sync states
        result = (
            self.db.client.table("room_sync_state")
            .select("*")
            .order("last_sync_at", desc=True)
            .execute()
        )

        rooms = [
            KnowledgeSyncState(
                room_id=row["room_id"],
                last_synced_version=row["last_synced_version"],
                last_sync_at=row.get("last_sync_at"),
            ).model_dump(mode="json")
            for row in result.data
        ]

        return {
            "server_version": server_version,
            "rooms": rooms,
        }
