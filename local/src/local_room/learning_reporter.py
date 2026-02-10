"""Buffered learning reporter for Local Room (Phase 5B).

Records observations from local task execution and sends them
to the server in batches.
"""

import logging
from datetime import datetime, UTC
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LocalLearning(BaseModel):
    """A single observation from local task execution."""

    category: str
    title: str
    content: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LearningReporter:
    """Buffers observations and reports them to the server.

    Deduplicates learnings by title within a session to avoid
    flooding the server with repeated observations.
    """

    def __init__(self, server_url: str, room_id: str) -> None:
        """Initialize the reporter.

        Args:
            server_url: The server's base URL
            room_id: This room's ID
        """
        self._server_url = server_url
        self._room_id = room_id
        self._buffer: list[LocalLearning] = []
        self._reported_titles: set[str] = set()
        self._total_reported: int = 0
        self._total_failed: int = 0

    @property
    def pending_count(self) -> int:
        """Number of learnings waiting to be flushed."""
        return len(self._buffer)

    def record(self, learning: LocalLearning) -> None:
        """Add a learning to the buffer.

        Skips if a learning with the same title has already been
        recorded in this session (deduplication).

        Args:
            learning: The observation to record
        """
        if learning.title in self._reported_titles:
            logger.debug(f"Skipping duplicate learning: {learning.title}")
            return

        self._buffer.append(learning)
        self._reported_titles.add(learning.title)
        logger.debug(f"Recorded learning: {learning.title}")

    async def flush(self) -> int:
        """Send buffered learnings to the server.

        On success, clears the buffer. On failure, keeps the buffer
        intact for retry on next flush.

        Returns:
            Number of learnings sent (0 if failed or empty)
        """
        if not self._buffer:
            return 0

        payload = {
            "room_id": self._room_id,
            "learnings": [
                {
                    "category": l.category,
                    "title": l.title,
                    "content": l.content,
                    "confidence": l.confidence,
                    "tags": l.tags,
                    "room_id": self._room_id,
                    "observed_at": l.observed_at.isoformat(),
                }
                for l in self._buffer
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._server_url}/knowledge/learnings",
                    json=payload,
                )

            if response.status_code == 200:
                count = len(self._buffer)
                self._total_reported += count
                self._buffer.clear()
                logger.info(f"Flushed {count} learnings to server")
                return count
            else:
                self._total_failed += len(self._buffer)
                logger.warning(
                    f"Failed to flush learnings: {response.status_code}"
                )
                return 0

        except httpx.ConnectError:
            logger.debug("Server unreachable for learning flush")
            return 0
        except Exception as e:
            self._total_failed += len(self._buffer)
            logger.error(f"Learning flush error: {e}")
            return 0

    def stats(self) -> dict[str, Any]:
        """Get reporter statistics.

        Returns:
            Dict with buffer size, totals, etc.
        """
        return {
            "pending": len(self._buffer),
            "total_reported": self._total_reported,
            "total_failed": self._total_failed,
            "unique_titles": len(self._reported_titles),
        }
