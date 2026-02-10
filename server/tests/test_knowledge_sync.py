"""Tests for knowledge sync layer (Phase 5B)."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.models.knowledge import KnowledgeCategory, KnowledgeSource
from loop_symphony.models.knowledge_sync import (
    KnowledgeSyncEntry,
    KnowledgeSyncPush,
    KnowledgeSyncState,
    LearningAggregationResult,
    RoomLearning,
    RoomLearningBatch,
)
from loop_symphony.manager.knowledge_sync_manager import (
    AGGREGATION_THRESHOLD,
    KnowledgeSyncManager,
)


# =============================================================================
# Model Tests
# =============================================================================


class TestKnowledgeSyncEntry:
    """Tests for KnowledgeSyncEntry model."""

    def test_basic_entry(self):
        entry = KnowledgeSyncEntry(
            id="abc-123",
            category="capabilities",
            title="Test",
            content="Test content",
            source="seed",
        )
        assert entry.id == "abc-123"
        assert entry.confidence == 1.0
        assert entry.version == 0
        assert entry.tags == []

    def test_all_fields(self):
        entry = KnowledgeSyncEntry(
            id="abc",
            category="patterns",
            title="Pattern X",
            content="Does X",
            source="error_tracker",
            confidence=0.8,
            tags=["learned"],
            version=5,
            updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert entry.confidence == 0.8
        assert entry.version == 5
        assert entry.tags == ["learned"]


class TestKnowledgeSyncPush:
    """Tests for KnowledgeSyncPush model."""

    def test_empty_push(self):
        push = KnowledgeSyncPush(server_version=10)
        assert push.server_version == 10
        assert push.entries == []
        assert push.removed_ids == []

    def test_push_with_entries(self):
        entry = KnowledgeSyncEntry(
            id="1", category="capabilities", title="T", content="C", source="seed"
        )
        push = KnowledgeSyncPush(
            server_version=5,
            entries=[entry],
            removed_ids=["old-1", "old-2"],
        )
        assert len(push.entries) == 1
        assert len(push.removed_ids) == 2


class TestKnowledgeSyncState:
    """Tests for KnowledgeSyncState model."""

    def test_defaults(self):
        state = KnowledgeSyncState(room_id="local-1")
        assert state.last_synced_version == 0
        assert state.last_sync_at is None

    def test_with_values(self):
        now = datetime.now(UTC)
        state = KnowledgeSyncState(
            room_id="local-1",
            last_synced_version=42,
            last_sync_at=now,
        )
        assert state.last_synced_version == 42
        assert state.last_sync_at == now


class TestRoomLearning:
    """Tests for RoomLearning model."""

    def test_basic_learning(self):
        learning = RoomLearning(
            category="patterns",
            title="Observed pattern",
            content="Something happened",
            room_id="local-1",
        )
        assert learning.confidence == 0.5
        assert learning.tags == []
        assert learning.room_id == "local-1"

    def test_confidence_validation(self):
        with pytest.raises(Exception):
            RoomLearning(
                category="patterns",
                title="T",
                content="C",
                room_id="r",
                confidence=1.5,
            )


class TestRoomLearningBatch:
    """Tests for RoomLearningBatch model."""

    def test_batch(self):
        learning = RoomLearning(
            category="patterns",
            title="T",
            content="C",
            room_id="local-1",
        )
        batch = RoomLearningBatch(
            room_id="local-1",
            learnings=[learning],
        )
        assert batch.room_id == "local-1"
        assert len(batch.learnings) == 1


class TestLearningAggregationResult:
    """Tests for LearningAggregationResult model."""

    def test_defaults(self):
        result = LearningAggregationResult()
        assert result.entries_created == 0
        assert result.entries_updated == 0
        assert result.learnings_processed == 0


# =============================================================================
# New KnowledgeSource Values
# =============================================================================


class TestNewKnowledgeSources:
    """Tests for new source values added in 5B."""

    def test_room_learning_source(self):
        assert KnowledgeSource.ROOM_LEARNING == "room_learning"

    def test_aggregated_source(self):
        assert KnowledgeSource.AGGREGATED == "aggregated"


# =============================================================================
# Database Method Tests (Mocked)
# =============================================================================


class TestSyncDatabaseMethods:
    """Tests for knowledge sync DB methods."""

    def _make_db(self):
        """Create a mock DatabaseClient."""
        db = AsyncMock()
        db.client = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_bump_knowledge_version(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        # Simulate existing version
        select_mock = MagicMock()
        select_mock.execute.return_value = MagicMock(data=[{"current_version": 5}])
        db.client.table.return_value.select.return_value.eq.return_value = select_mock
        db.client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

        # Call the real method
        result = await DatabaseClient.bump_knowledge_version(db)
        assert result == 6

    @pytest.mark.asyncio
    async def test_get_knowledge_version(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        select_mock = MagicMock()
        select_mock.execute.return_value = MagicMock(data=[{"current_version": 10}])
        db.client.table.return_value.select.return_value.eq.return_value = select_mock

        result = await DatabaseClient.get_knowledge_version(db)
        assert result == 10

    @pytest.mark.asyncio
    async def test_get_knowledge_version_default(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        select_mock = MagicMock()
        select_mock.execute.return_value = MagicMock(data=[])
        db.client.table.return_value.select.return_value.eq.return_value = select_mock

        result = await DatabaseClient.get_knowledge_version(db)
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_entries_since_version(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        entries = [
            {"id": "1", "category": "capabilities", "title": "T", "version": 3},
        ]
        order_mock = MagicMock()
        order_mock.execute.return_value = MagicMock(data=entries)
        eq_mock = MagicMock()
        eq_mock.order.return_value = order_mock
        gt_mock = MagicMock()
        gt_mock.eq.return_value = eq_mock
        db.client.table.return_value.select.return_value.gt.return_value = gt_mock

        result = await DatabaseClient.get_entries_since_version(db, since_version=2)
        assert len(result) == 1
        assert result[0]["version"] == 3

    @pytest.mark.asyncio
    async def test_get_room_sync_state(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        state_data = {"room_id": "local-1", "last_synced_version": 5}
        execute_mock = MagicMock()
        execute_mock.execute.return_value = MagicMock(data=[state_data])
        db.client.table.return_value.select.return_value.eq.return_value = execute_mock

        result = await DatabaseClient.get_room_sync_state(db, room_id="local-1")
        assert result["last_synced_version"] == 5

    @pytest.mark.asyncio
    async def test_update_room_sync_state(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        db.client.table.return_value.upsert.return_value.execute = MagicMock()

        await DatabaseClient.update_room_sync_state(db, room_id="local-1", version=10)
        db.client.table.return_value.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_room_learnings(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        insert_data = [{"title": "T1"}, {"title": "T2"}]
        db.client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=insert_data
        )

        result = await DatabaseClient.create_room_learnings(db, learnings=insert_data)
        assert result == 2

    @pytest.mark.asyncio
    async def test_create_room_learnings_empty(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        result = await DatabaseClient.create_room_learnings(db, learnings=[])
        assert result == 0

    @pytest.mark.asyncio
    async def test_mark_learnings_processed(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        db.client = MagicMock()

        db.client.table.return_value.update.return_value.in_.return_value.execute.return_value = MagicMock(
            data=[{"id": "1"}, {"id": "2"}]
        )

        result = await DatabaseClient.mark_learnings_processed(db, ids=["1", "2"])
        assert result == 2

    @pytest.mark.asyncio
    async def test_mark_learnings_processed_empty(self):
        from loop_symphony.db.client import DatabaseClient

        db = MagicMock(spec=DatabaseClient)
        result = await DatabaseClient.mark_learnings_processed(db, ids=[])
        assert result == 0


# =============================================================================
# Knowledge Sync Manager Tests
# =============================================================================


class TestKnowledgeSyncManagerGetSyncPush:
    """Tests for sync push generation."""

    @pytest.mark.asyncio
    async def test_push_for_new_room(self):
        db = AsyncMock()
        db.get_room_sync_state.return_value = None
        db.get_knowledge_version.return_value = 5
        db.get_entries_since_version.return_value = [
            {
                "id": "entry-1",
                "category": "capabilities",
                "title": "Can reason",
                "content": "Full reasoning capability",
                "source": "seed",
                "confidence": 1.0,
                "tags": [],
                "version": 1,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        ]
        db.get_removed_since_version.return_value = []

        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        push = await manager.get_sync_push("local-1")
        assert push.server_version == 5
        assert len(push.entries) == 1
        assert push.entries[0].id == "entry-1"

    @pytest.mark.asyncio
    async def test_push_when_up_to_date(self):
        db = AsyncMock()
        db.get_room_sync_state.return_value = {"last_synced_version": 10}
        db.get_knowledge_version.return_value = 10

        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        push = await manager.get_sync_push("local-1")
        assert push.server_version == 10
        assert push.entries == []
        assert push.removed_ids == []

    @pytest.mark.asyncio
    async def test_push_includes_removals(self):
        db = AsyncMock()
        db.get_room_sync_state.return_value = {"last_synced_version": 3}
        db.get_knowledge_version.return_value = 5
        db.get_entries_since_version.return_value = []
        db.get_removed_since_version.return_value = ["old-1", "old-2"]

        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        push = await manager.get_sync_push("local-1")
        assert push.removed_ids == ["old-1", "old-2"]


class TestKnowledgeSyncManagerRecordSync:
    """Tests for sync recording."""

    @pytest.mark.asyncio
    async def test_record_sync(self):
        db = AsyncMock()
        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        await manager.record_sync("local-1", 10)
        db.update_room_sync_state.assert_called_once_with("local-1", 10)


class TestKnowledgeSyncManagerAcceptLearnings:
    """Tests for learning acceptance."""

    @pytest.mark.asyncio
    async def test_accept_learnings(self):
        db = AsyncMock()
        db.create_room_learnings.return_value = 2
        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        batch = RoomLearningBatch(
            room_id="local-1",
            learnings=[
                RoomLearning(
                    category="patterns",
                    title="Pattern A",
                    content="Observed A",
                    room_id="local-1",
                ),
                RoomLearning(
                    category="patterns",
                    title="Pattern B",
                    content="Observed B",
                    room_id="local-1",
                ),
            ],
        )

        count = await manager.accept_learnings(batch)
        assert count == 2
        db.create_room_learnings.assert_called_once()

    @pytest.mark.asyncio
    async def test_accept_empty_batch(self):
        db = AsyncMock()
        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        batch = RoomLearningBatch(room_id="local-1", learnings=[])
        count = await manager.accept_learnings(batch)
        assert count == 0


class TestKnowledgeSyncManagerAggregation:
    """Tests for learning aggregation."""

    @pytest.mark.asyncio
    async def test_aggregation_empty(self):
        db = AsyncMock()
        db.get_unprocessed_learnings.return_value = []
        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        result = await manager.aggregate_learnings()
        assert result.learnings_processed == 0
        assert result.entries_created == 0

    @pytest.mark.asyncio
    async def test_aggregation_single_room(self):
        """Single room learning → ROOM_LEARNING source."""
        db = AsyncMock()
        db.get_unprocessed_learnings.return_value = [
            {
                "id": "l1",
                "room_id": "local-1",
                "category": "patterns",
                "title": "Pattern X",
                "content": "Observed X",
                "confidence": 0.6,
                "tags": [],
            },
        ]
        db.create_knowledge_entry.return_value = {"id": "new-1"}
        db.mark_learnings_processed.return_value = 1
        # Stub version bumping
        db.bump_knowledge_version = AsyncMock(return_value=1)
        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        result = await manager.aggregate_learnings()
        assert result.entries_created == 1
        assert result.learnings_processed == 1

        # Check it used ROOM_LEARNING source
        call_args = db.create_knowledge_entry.call_args[0][0]
        assert call_args["source"] == KnowledgeSource.ROOM_LEARNING.value

    @pytest.mark.asyncio
    async def test_aggregation_multi_room(self):
        """3+ rooms → AGGREGATED source with boosted confidence."""
        db = AsyncMock()
        db.get_unprocessed_learnings.return_value = [
            {
                "id": f"l{i}",
                "room_id": f"room-{i}",
                "category": "patterns",
                "title": "Common Pattern",
                "content": "Many rooms see this",
                "confidence": 0.5,
                "tags": [],
            }
            for i in range(AGGREGATION_THRESHOLD)
        ]
        db.create_knowledge_entry.return_value = {"id": "agg-1"}
        db.mark_learnings_processed.return_value = AGGREGATION_THRESHOLD
        db.bump_knowledge_version = AsyncMock(return_value=1)
        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        result = await manager.aggregate_learnings()
        assert result.entries_created == 1
        assert result.learnings_processed == AGGREGATION_THRESHOLD

        # Check it used AGGREGATED source
        call_args = db.create_knowledge_entry.call_args[0][0]
        assert call_args["source"] == KnowledgeSource.AGGREGATED.value
        # Confidence should be boosted
        assert call_args["confidence"] > 0.5

    @pytest.mark.asyncio
    async def test_aggregation_groups_by_title(self):
        """Different titles → separate entries."""
        db = AsyncMock()
        db.get_unprocessed_learnings.return_value = [
            {
                "id": "l1",
                "room_id": "local-1",
                "category": "patterns",
                "title": "Pattern A",
                "content": "A",
                "confidence": 0.5,
                "tags": [],
            },
            {
                "id": "l2",
                "room_id": "local-1",
                "category": "boundaries",
                "title": "Boundary B",
                "content": "B",
                "confidence": 0.5,
                "tags": [],
            },
        ]
        db.create_knowledge_entry.return_value = {"id": "new"}
        db.mark_learnings_processed.return_value = 2
        db.bump_knowledge_version = AsyncMock(return_value=1)
        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        result = await manager.aggregate_learnings()
        assert result.entries_created == 2
        assert result.learnings_processed == 2


class TestKnowledgeSyncManagerStatus:
    """Tests for sync status."""

    @pytest.mark.asyncio
    async def test_get_sync_status(self):
        db = AsyncMock()
        db.get_knowledge_version.return_value = 15
        db.client = MagicMock()

        # Mock the direct table query for room states
        order_mock = MagicMock()
        order_mock.execute.return_value = MagicMock(data=[
            {
                "room_id": "local-1",
                "last_synced_version": 10,
                "last_sync_at": datetime.now(UTC).isoformat(),
            },
        ])
        db.client.table.return_value.select.return_value.order.return_value = order_mock

        km = AsyncMock()
        manager = KnowledgeSyncManager(db=db, knowledge_manager=km)

        status = await manager.get_sync_status()
        assert status["server_version"] == 15
        assert len(status["rooms"]) == 1
        assert status["rooms"][0]["room_id"] == "local-1"


# =============================================================================
# Endpoint Tests (direct function calls with mock dependencies)
# =============================================================================


class TestSyncEndpoints:
    """Tests for knowledge sync API endpoints."""

    @pytest.mark.asyncio
    async def test_accept_learnings_endpoint(self):
        """POST /knowledge/learnings accepts room learnings."""
        from loop_symphony.api.routes import accept_learnings

        mock_sync = AsyncMock(spec=KnowledgeSyncManager)
        mock_sync.accept_learnings.return_value = 2

        batch = RoomLearningBatch(
            room_id="local-1",
            learnings=[
                RoomLearning(
                    category="patterns",
                    title="T",
                    content="C",
                    room_id="local-1",
                ),
            ],
        )

        result = await accept_learnings(batch=batch, sync_manager=mock_sync)
        assert result["accepted"] == 2
        assert result["room_id"] == "local-1"
        mock_sync.accept_learnings.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregate_endpoint(self):
        """POST /knowledge/aggregate triggers aggregation."""
        from loop_symphony.api.routes import aggregate_learnings

        mock_sync = AsyncMock(spec=KnowledgeSyncManager)
        mock_sync.aggregate_learnings.return_value = LearningAggregationResult(
            entries_created=3, learnings_processed=10
        )

        result = await aggregate_learnings(sync_manager=mock_sync)
        assert result.entries_created == 3
        assert result.learnings_processed == 10

    @pytest.mark.asyncio
    async def test_sync_status_endpoint(self):
        """GET /knowledge/sync/status returns sync status."""
        from loop_symphony.api.routes import sync_status

        mock_sync = AsyncMock(spec=KnowledgeSyncManager)
        mock_sync.get_sync_status.return_value = {
            "server_version": 5,
            "rooms": [],
        }

        result = await sync_status(sync_manager=mock_sync)
        assert result["server_version"] == 5
        assert result["rooms"] == []


class TestHeartbeatKnowledgeSync:
    """Tests for knowledge sync piggybacked on heartbeat."""

    @pytest.mark.asyncio
    async def test_heartbeat_without_knowledge_version(self):
        """Heartbeat without last_knowledge_version returns no updates."""
        from loop_symphony.api.routes import room_heartbeat
        from loop_symphony.manager.room_registry import RoomHeartbeat, RoomRegistry

        mock_registry = MagicMock(spec=RoomRegistry)
        mock_registry.heartbeat.return_value = True

        mock_sync = AsyncMock(spec=KnowledgeSyncManager)

        hb = RoomHeartbeat(room_id="local-1", status="online")
        result = await room_heartbeat(
            heartbeat=hb,
            room_registry=mock_registry,
            sync_manager=mock_sync,
        )

        assert result["status"] == "ok"
        assert "knowledge_updates" not in result
        mock_sync.get_sync_push.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_with_knowledge_version_has_updates(self):
        """Heartbeat with last_knowledge_version includes sync push."""
        from loop_symphony.api.routes import room_heartbeat
        from loop_symphony.manager.room_registry import RoomHeartbeat, RoomRegistry

        mock_registry = MagicMock(spec=RoomRegistry)
        mock_registry.heartbeat.return_value = True

        push = KnowledgeSyncPush(
            server_version=5,
            entries=[
                KnowledgeSyncEntry(
                    id="e1",
                    category="capabilities",
                    title="T",
                    content="C",
                    source="seed",
                    version=5,
                )
            ],
        )
        mock_sync = AsyncMock(spec=KnowledgeSyncManager)
        mock_sync.get_sync_push.return_value = push

        hb = RoomHeartbeat(
            room_id="local-1",
            status="online",
            last_knowledge_version=0,
        )
        result = await room_heartbeat(
            heartbeat=hb,
            room_registry=mock_registry,
            sync_manager=mock_sync,
        )

        assert result["knowledge_updates"] is not None
        assert result["knowledge_updates"]["server_version"] == 5
        mock_sync.record_sync.assert_called_once_with("local-1", 5)

    @pytest.mark.asyncio
    async def test_heartbeat_with_knowledge_version_no_updates(self):
        """Heartbeat when room is already up to date."""
        from loop_symphony.api.routes import room_heartbeat
        from loop_symphony.manager.room_registry import RoomHeartbeat, RoomRegistry

        mock_registry = MagicMock(spec=RoomRegistry)
        mock_registry.heartbeat.return_value = True

        push = KnowledgeSyncPush(server_version=5)  # Empty entries/removals
        mock_sync = AsyncMock(spec=KnowledgeSyncManager)
        mock_sync.get_sync_push.return_value = push

        hb = RoomHeartbeat(
            room_id="local-1",
            status="online",
            last_knowledge_version=5,
        )
        result = await room_heartbeat(
            heartbeat=hb,
            room_registry=mock_registry,
            sync_manager=mock_sync,
        )

        assert result["knowledge_updates"] is None
        mock_sync.record_sync.assert_not_called()
