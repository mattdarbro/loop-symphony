"""Tests for knowledge sync in Local Room (Phase 5B)."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from local_room.knowledge_cache import CachedKnowledgeEntry, KnowledgeCache
from local_room.learning_reporter import LearningReporter, LocalLearning


# =============================================================================
# Knowledge Cache Tests
# =============================================================================


class TestCachedKnowledgeEntry:
    """Tests for CachedKnowledgeEntry model."""

    def test_basic_entry(self):
        entry = CachedKnowledgeEntry(
            id="abc-123",
            category="capabilities",
            title="Can reason",
            content="Full reasoning capability",
            source="seed",
        )
        assert entry.id == "abc-123"
        assert entry.confidence == 1.0
        assert entry.version == 0
        assert entry.tags == []

    def test_all_fields(self):
        entry = CachedKnowledgeEntry(
            id="xyz",
            category="patterns",
            title="Pattern X",
            content="Does X",
            source="error_tracker",
            confidence=0.8,
            tags=["learned"],
            version=5,
        )
        assert entry.confidence == 0.8
        assert entry.tags == ["learned"]


class TestKnowledgeCacheInit:
    """Tests for KnowledgeCache initialization."""

    def test_empty_cache(self):
        cache = KnowledgeCache()
        assert cache.server_version == 0
        assert cache.get_entries() == []

    def test_stats_empty(self):
        cache = KnowledgeCache()
        stats = cache.stats()
        assert stats["total_entries"] == 0
        assert stats["server_version"] == 0
        assert stats["by_category"] == {}


class TestKnowledgeCacheApplySync:
    """Tests for applying sync pushes."""

    def test_apply_new_entries(self):
        cache = KnowledgeCache()
        changes = cache.apply_sync({
            "server_version": 5,
            "entries": [
                {
                    "id": "e1",
                    "category": "capabilities",
                    "title": "Cap 1",
                    "content": "Content 1",
                    "source": "seed",
                    "confidence": 1.0,
                    "tags": [],
                    "version": 1,
                },
                {
                    "id": "e2",
                    "category": "patterns",
                    "title": "Pattern 1",
                    "content": "Content 2",
                    "source": "seed",
                    "version": 2,
                },
            ],
            "removed_ids": [],
        })

        assert changes == 2
        assert cache.server_version == 5
        assert len(cache.get_entries()) == 2

    def test_apply_updates_existing(self):
        cache = KnowledgeCache()
        cache.apply_sync({
            "server_version": 1,
            "entries": [
                {
                    "id": "e1",
                    "category": "capabilities",
                    "title": "Old title",
                    "content": "Old content",
                    "source": "seed",
                },
            ],
        })

        # Update same entry
        changes = cache.apply_sync({
            "server_version": 2,
            "entries": [
                {
                    "id": "e1",
                    "category": "capabilities",
                    "title": "New title",
                    "content": "New content",
                    "source": "seed",
                },
            ],
        })

        assert changes == 1
        entries = cache.get_entries()
        assert len(entries) == 1
        assert entries[0].title == "New title"

    def test_apply_removals(self):
        cache = KnowledgeCache()
        cache.apply_sync({
            "server_version": 1,
            "entries": [
                {"id": "e1", "category": "capabilities", "title": "T", "content": "C", "source": "seed"},
                {"id": "e2", "category": "patterns", "title": "T2", "content": "C2", "source": "seed"},
            ],
        })
        assert len(cache.get_entries()) == 2

        changes = cache.apply_sync({
            "server_version": 2,
            "entries": [],
            "removed_ids": ["e1"],
        })

        assert changes == 1
        assert len(cache.get_entries()) == 1
        assert cache.get_entries()[0].id == "e2"

    def test_apply_empty_push(self):
        cache = KnowledgeCache()
        changes = cache.apply_sync({
            "server_version": 0,
            "entries": [],
            "removed_ids": [],
        })
        assert changes == 0

    def test_version_only_increases(self):
        cache = KnowledgeCache()
        cache.apply_sync({"server_version": 10, "entries": []})
        assert cache.server_version == 10

        cache.apply_sync({"server_version": 5, "entries": []})
        assert cache.server_version == 10  # Didn't decrease


class TestKnowledgeCacheGetEntries:
    """Tests for entry retrieval."""

    def _populated_cache(self) -> KnowledgeCache:
        cache = KnowledgeCache()
        cache.apply_sync({
            "server_version": 3,
            "entries": [
                {"id": "e1", "category": "capabilities", "title": "Cap", "content": "C", "source": "seed"},
                {"id": "e2", "category": "patterns", "title": "Pat", "content": "P", "source": "seed"},
                {"id": "e3", "category": "capabilities", "title": "Cap2", "content": "C2", "source": "seed"},
            ],
        })
        return cache

    def test_get_all(self):
        cache = self._populated_cache()
        assert len(cache.get_entries()) == 3

    def test_filter_by_category(self):
        cache = self._populated_cache()
        caps = cache.get_entries(category="capabilities")
        assert len(caps) == 2
        assert all(e.category == "capabilities" for e in caps)

    def test_filter_nonexistent_category(self):
        cache = self._populated_cache()
        assert cache.get_entries(category="nonexistent") == []


class TestKnowledgeCacheContextSummary:
    """Tests for context summary rendering."""

    def test_empty_context(self):
        cache = KnowledgeCache()
        summary = cache.get_context_summary()
        assert "No knowledge entries" in summary

    def test_context_with_entries(self):
        cache = KnowledgeCache()
        cache.apply_sync({
            "server_version": 1,
            "entries": [
                {
                    "id": "e1",
                    "category": "capabilities",
                    "title": "Can reason",
                    "content": "Full reasoning",
                    "source": "seed",
                    "confidence": 1.0,
                },
            ],
        })

        summary = cache.get_context_summary()
        assert "Can reason" in summary
        assert "Full reasoning" in summary

    def test_context_filter_categories(self):
        cache = KnowledgeCache()
        cache.apply_sync({
            "server_version": 1,
            "entries": [
                {"id": "e1", "category": "capabilities", "title": "Cap", "content": "C1", "source": "seed"},
                {"id": "e2", "category": "boundaries", "title": "Bound", "content": "B1", "source": "seed"},
            ],
        })

        summary = cache.get_context_summary(categories=["capabilities"])
        assert "Cap" in summary
        assert "Bound" not in summary

    def test_context_shows_low_confidence(self):
        cache = KnowledgeCache()
        cache.apply_sync({
            "server_version": 1,
            "entries": [
                {
                    "id": "e1",
                    "category": "patterns",
                    "title": "Maybe",
                    "content": "Uncertain",
                    "source": "room_learning",
                    "confidence": 0.6,
                },
            ],
        })

        summary = cache.get_context_summary()
        assert "60%" in summary

    def test_stats_with_entries(self):
        cache = KnowledgeCache()
        cache.apply_sync({
            "server_version": 3,
            "entries": [
                {"id": "e1", "category": "capabilities", "title": "T1", "content": "C", "source": "seed"},
                {"id": "e2", "category": "capabilities", "title": "T2", "content": "C", "source": "seed"},
                {"id": "e3", "category": "patterns", "title": "T3", "content": "C", "source": "seed"},
            ],
        })

        stats = cache.stats()
        assert stats["total_entries"] == 3
        assert stats["server_version"] == 3
        assert stats["by_category"]["capabilities"] == 2
        assert stats["by_category"]["patterns"] == 1


# =============================================================================
# Learning Reporter Tests
# =============================================================================


class TestLocalLearning:
    """Tests for LocalLearning model."""

    def test_basic_learning(self):
        learning = LocalLearning(
            category="patterns",
            title="Observed X",
            content="X happened",
        )
        assert learning.confidence == 0.5
        assert learning.tags == []
        assert isinstance(learning.observed_at, datetime)

    def test_custom_fields(self):
        learning = LocalLearning(
            category="boundaries",
            title="Limit Y",
            content="Can't do Y",
            confidence=0.8,
            tags=["limitation"],
        )
        assert learning.confidence == 0.8
        assert learning.tags == ["limitation"]


class TestLearningReporterInit:
    """Tests for LearningReporter initialization."""

    def test_init(self):
        reporter = LearningReporter(
            server_url="http://localhost:8000",
            room_id="local-1",
        )
        assert reporter.pending_count == 0
        assert reporter.stats()["total_reported"] == 0


class TestLearningReporterRecord:
    """Tests for recording learnings."""

    def test_record_learning(self):
        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        learning = LocalLearning(category="patterns", title="P1", content="C1")
        reporter.record(learning)
        assert reporter.pending_count == 1

    def test_record_dedup(self):
        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        l1 = LocalLearning(category="patterns", title="Same Title", content="C1")
        l2 = LocalLearning(category="patterns", title="Same Title", content="C2")
        reporter.record(l1)
        reporter.record(l2)
        assert reporter.pending_count == 1

    def test_record_different_titles(self):
        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        l1 = LocalLearning(category="patterns", title="Title A", content="C1")
        l2 = LocalLearning(category="patterns", title="Title B", content="C2")
        reporter.record(l1)
        reporter.record(l2)
        assert reporter.pending_count == 2


class TestLearningReporterFlush:
    """Tests for flushing learnings to server."""

    @pytest.mark.asyncio
    async def test_flush_empty(self):
        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        count = await reporter.flush()
        assert count == 0

    @pytest.mark.asyncio
    async def test_flush_success(self):
        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        reporter.record(LocalLearning(category="patterns", title="P1", content="C1"))
        reporter.record(LocalLearning(category="patterns", title="P2", content="C2"))

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("local_room.learning_reporter.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await reporter.flush()

        assert count == 2
        assert reporter.pending_count == 0
        assert reporter.stats()["total_reported"] == 2

    @pytest.mark.asyncio
    async def test_flush_failure_keeps_buffer(self):
        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        reporter.record(LocalLearning(category="patterns", title="P1", content="C1"))

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("local_room.learning_reporter.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await reporter.flush()

        assert count == 0
        assert reporter.pending_count == 1  # Still buffered

    @pytest.mark.asyncio
    async def test_flush_connection_error_keeps_buffer(self):
        import httpx

        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        reporter.record(LocalLearning(category="patterns", title="P1", content="C1"))

        with patch("local_room.learning_reporter.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.ConnectError("unreachable")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await reporter.flush()

        assert count == 0
        assert reporter.pending_count == 1  # Still buffered


class TestLearningReporterStats:
    """Tests for reporter statistics."""

    def test_stats_after_records(self):
        reporter = LearningReporter(server_url="http://localhost:8000", room_id="local-1")
        reporter.record(LocalLearning(category="patterns", title="A", content="C"))
        reporter.record(LocalLearning(category="patterns", title="B", content="C"))

        stats = reporter.stats()
        assert stats["pending"] == 2
        assert stats["unique_titles"] == 2
        assert stats["total_reported"] == 0


# =============================================================================
# Local Room Integration Tests
# =============================================================================


class TestLocalRoomKnowledgeIntegration:
    """Tests for knowledge sync integration in LocalRoom."""

    def test_room_has_cache_and_reporter(self):
        """LocalRoom should have knowledge_cache and learning_reporter."""
        from local_room.config import LocalRoomConfig
        from local_room.room import LocalRoom

        config = LocalRoomConfig()
        room = LocalRoom(config)

        assert room.knowledge_cache is not None
        assert room.learning_reporter is not None
        assert isinstance(room.knowledge_cache, KnowledgeCache)
        assert isinstance(room.learning_reporter, LearningReporter)

    def test_cache_starts_empty(self):
        from local_room.config import LocalRoomConfig
        from local_room.room import LocalRoom

        config = LocalRoomConfig()
        room = LocalRoom(config)

        assert room.knowledge_cache.server_version == 0
        assert room.knowledge_cache.get_entries() == []


class TestLocalRoomHeartbeatSync:
    """Tests for heartbeat-based knowledge sync."""

    @pytest.mark.asyncio
    async def test_heartbeat_sends_knowledge_version(self):
        """Heartbeat should include last_knowledge_version."""
        from local_room.config import LocalRoomConfig
        from local_room.room import LocalRoom

        config = LocalRoomConfig()
        room = LocalRoom(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "room_id": config.room_id}

        with patch("local_room.room.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            # Mock ollama health check
            room._ollama.health_check = AsyncMock(return_value={"healthy": True})

            result = await room._send_heartbeat()
            assert result is True

            # Verify the payload included last_knowledge_version
            call_args = mock_instance.post.call_args
            payload = call_args[1]["json"]
            assert "last_knowledge_version" in payload
            assert payload["last_knowledge_version"] == 0

    @pytest.mark.asyncio
    async def test_heartbeat_applies_knowledge_updates(self):
        """Heartbeat response with knowledge_updates should update cache."""
        from local_room.config import LocalRoomConfig
        from local_room.room import LocalRoom

        config = LocalRoomConfig()
        room = LocalRoom(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "room_id": config.room_id,
            "knowledge_updates": {
                "server_version": 5,
                "entries": [
                    {
                        "id": "e1",
                        "category": "capabilities",
                        "title": "Can reason",
                        "content": "Full reasoning",
                        "source": "seed",
                        "confidence": 1.0,
                        "tags": [],
                        "version": 1,
                    }
                ],
                "removed_ids": [],
            },
        }

        with patch("local_room.room.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            room._ollama.health_check = AsyncMock(return_value={"healthy": True})

            result = await room._send_heartbeat()
            assert result is True

        # Cache should be updated
        assert room.knowledge_cache.server_version == 5
        entries = room.knowledge_cache.get_entries()
        assert len(entries) == 1
        assert entries[0].title == "Can reason"

    @pytest.mark.asyncio
    async def test_heartbeat_no_updates_null(self):
        """Heartbeat response with knowledge_updates=null should not crash."""
        from local_room.config import LocalRoomConfig
        from local_room.room import LocalRoom

        config = LocalRoomConfig()
        room = LocalRoom(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "room_id": config.room_id,
            "knowledge_updates": None,
        }

        with patch("local_room.room.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            room._ollama.health_check = AsyncMock(return_value={"healthy": True})

            result = await room._send_heartbeat()
            assert result is True

        assert room.knowledge_cache.server_version == 0  # Unchanged
