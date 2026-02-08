"""Tests for knowledge layer (Phase 5A)."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

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
from loop_symphony.manager.knowledge_manager import KnowledgeManager
from loop_symphony.manager.knowledge_seed import (
    BOUNDARIES_SEED,
    CAPABILITIES_SEED,
    CHANGELOG_SEED,
    PATTERNS_SEED,
    seed_knowledge,
)


# =============================================================================
# Model Tests
# =============================================================================


class TestKnowledgeCategory:
    """Tests for KnowledgeCategory enum."""

    def test_all_categories_defined(self):
        assert KnowledgeCategory.CAPABILITIES == "capabilities"
        assert KnowledgeCategory.BOUNDARIES == "boundaries"
        assert KnowledgeCategory.PATTERNS == "patterns"
        assert KnowledgeCategory.CHANGELOG == "changelog"
        assert KnowledgeCategory.USER == "user"

    def test_category_titles(self):
        for cat in KnowledgeCategory:
            assert cat in CATEGORY_TITLES


class TestKnowledgeSource:
    """Tests for KnowledgeSource enum."""

    def test_all_sources_defined(self):
        assert KnowledgeSource.SEED == "seed"
        assert KnowledgeSource.ERROR_TRACKER == "error_tracker"
        assert KnowledgeSource.ARRANGEMENT_TRACKER == "arrangement_tracker"
        assert KnowledgeSource.TRUST_TRACKER == "trust_tracker"
        assert KnowledgeSource.MANUAL == "manual"
        assert KnowledgeSource.SYSTEM == "system"


class TestKnowledgeEntry:
    """Tests for KnowledgeEntry model."""

    def test_basic_entry(self):
        entry = KnowledgeEntry(
            category=KnowledgeCategory.CAPABILITIES,
            title="Test capability",
            content="This is a test.",
        )
        assert entry.category == KnowledgeCategory.CAPABILITIES
        assert entry.title == "Test capability"
        assert entry.confidence == 1.0
        assert entry.source == KnowledgeSource.SEED
        assert entry.user_id is None
        assert entry.tags == []
        assert entry.is_active is True
        assert isinstance(entry.id, UUID)

    def test_entry_with_all_fields(self):
        entry = KnowledgeEntry(
            category=KnowledgeCategory.USER,
            title="User preference",
            content="Prefers research over note.",
            source=KnowledgeSource.TRUST_TRACKER,
            confidence=0.85,
            user_id="user-123",
            tags=["preference", "routing"],
        )
        assert entry.user_id == "user-123"
        assert entry.confidence == 0.85
        assert "preference" in entry.tags

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            KnowledgeEntry(
                category=KnowledgeCategory.CAPABILITIES,
                title="Bad",
                content="Bad",
                confidence=1.5,
            )
        with pytest.raises(Exception):
            KnowledgeEntry(
                category=KnowledgeCategory.CAPABILITIES,
                title="Bad",
                content="Bad",
                confidence=-0.1,
            )

    def test_serialization(self):
        entry = KnowledgeEntry(
            category=KnowledgeCategory.PATTERNS,
            title="Test",
            content="Content",
        )
        d = entry.model_dump(mode="json")
        assert d["category"] == "patterns"
        assert d["source"] == "seed"
        assert "id" in d


class TestKnowledgeFile:
    """Tests for KnowledgeFile model."""

    def test_empty_file(self):
        kf = KnowledgeFile(
            category=KnowledgeCategory.CAPABILITIES,
            title="Capabilities",
            markdown="# Capabilities\n",
            entries=[],
        )
        assert kf.last_updated is None
        assert len(kf.entries) == 0

    def test_file_with_entries(self):
        entry = KnowledgeEntry(
            category=KnowledgeCategory.CAPABILITIES,
            title="Test",
            content="Test content",
        )
        kf = KnowledgeFile(
            category=KnowledgeCategory.CAPABILITIES,
            title="Capabilities",
            markdown="# Capabilities\n\n## Test\nTest content",
            entries=[entry],
            last_updated=datetime.now(UTC),
        )
        assert len(kf.entries) == 1
        assert kf.last_updated is not None


class TestUserKnowledge:
    """Tests for UserKnowledge model."""

    def test_default_values(self):
        uk = UserKnowledge(user_id="user-123")
        assert uk.trust_level == 0
        assert uk.total_tasks == 0
        assert uk.success_rate == 0.0
        assert uk.preferred_patterns == []
        assert uk.entries == []
        assert uk.markdown == ""

    def test_populated_user(self):
        uk = UserKnowledge(
            user_id="user-456",
            trust_level=2,
            total_tasks=50,
            success_rate=0.92,
            preferred_patterns=["research-synthesis"],
        )
        assert uk.trust_level == 2
        assert uk.success_rate == 0.92


class TestKnowledgeEntryCreate:
    """Tests for entry creation request model."""

    def test_basic_create(self):
        create = KnowledgeEntryCreate(
            category=KnowledgeCategory.PATTERNS,
            title="New pattern",
            content="A new pattern was discovered.",
        )
        assert create.confidence == 1.0
        assert create.user_id is None
        assert create.tags == []

    def test_create_with_options(self):
        create = KnowledgeEntryCreate(
            category=KnowledgeCategory.USER,
            title="User pref",
            content="User prefers concise answers.",
            confidence=0.9,
            user_id="user-abc",
            tags=["preference"],
        )
        assert create.user_id == "user-abc"


class TestKnowledgeRefreshResult:
    """Tests for refresh result model."""

    def test_default_result(self):
        result = KnowledgeRefreshResult()
        assert result.entries_created == 0
        assert result.entries_removed == 0
        assert result.sources_refreshed == []

    def test_populated_result(self):
        result = KnowledgeRefreshResult(
            entries_created=10,
            entries_removed=3,
            sources_refreshed=["error_tracker", "arrangement_tracker"],
        )
        assert result.entries_created == 10
        assert len(result.sources_refreshed) == 2


# =============================================================================
# Seed Data Tests
# =============================================================================


class TestKnowledgeSeed:
    """Tests for seed data and seeder function."""

    def test_capabilities_seed_not_empty(self):
        assert len(CAPABILITIES_SEED) >= 5
        for entry in CAPABILITIES_SEED:
            assert "title" in entry
            assert "content" in entry
            assert "tags" in entry

    def test_boundaries_seed_not_empty(self):
        assert len(BOUNDARIES_SEED) >= 4
        for entry in BOUNDARIES_SEED:
            assert "title" in entry
            assert "content" in entry

    def test_patterns_seed_not_empty(self):
        assert len(PATTERNS_SEED) >= 3

    def test_changelog_seed_not_empty(self):
        assert len(CHANGELOG_SEED) >= 3

    @pytest.mark.asyncio
    async def test_seed_creates_entries(self):
        """Seeder creates entries when DB is empty."""
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=[])
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        count = await seed_knowledge(mock_db)

        expected = (
            len(CAPABILITIES_SEED)
            + len(BOUNDARIES_SEED)
            + len(PATTERNS_SEED)
            + len(CHANGELOG_SEED)
        )
        assert count == expected
        assert mock_db.create_knowledge_entry.call_count == expected

    @pytest.mark.asyncio
    async def test_seed_idempotent(self):
        """Seeder skips categories that already have seed entries."""
        mock_db = AsyncMock()
        # Return existing entries for all categories
        mock_db.list_knowledge_entries = AsyncMock(
            return_value=[{"id": str(uuid4()), "title": "Existing"}]
        )
        mock_db.create_knowledge_entry = AsyncMock()

        count = await seed_knowledge(mock_db)

        assert count == 0
        mock_db.create_knowledge_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_partial(self):
        """Seeder only fills missing categories."""
        mock_db = AsyncMock()

        call_count = 0

        async def mock_list(category=None, source=None, user_id=None):
            # Only capabilities has existing entries
            if category == "capabilities":
                return [{"id": str(uuid4())}]
            return []

        mock_db.list_knowledge_entries = AsyncMock(side_effect=mock_list)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        count = await seed_knowledge(mock_db)

        # Should create entries for boundaries, patterns, changelog (not capabilities)
        expected = len(BOUNDARIES_SEED) + len(PATTERNS_SEED) + len(CHANGELOG_SEED)
        assert count == expected


# =============================================================================
# Knowledge Manager Tests
# =============================================================================


def _make_db_row(
    category: str = "capabilities",
    title: str = "Test entry",
    content: str = "Test content",
    source: str = "seed",
    confidence: float = 1.0,
    user_id: str | None = None,
    tags: list | None = None,
) -> dict:
    """Create a mock DB row."""
    return {
        "id": str(uuid4()),
        "category": category,
        "title": title,
        "content": content,
        "source": source,
        "confidence": confidence,
        "user_id": user_id,
        "tags": tags or [],
        "is_active": True,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }


class TestKnowledgeManagerGetFile:
    """Tests for KnowledgeManager.get_file()."""

    @pytest.mark.asyncio
    async def test_get_empty_file(self):
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=[])

        km = KnowledgeManager(db=mock_db)
        result = await km.get_file(KnowledgeCategory.CAPABILITIES)

        assert result.category == KnowledgeCategory.CAPABILITIES
        assert result.title == "Capabilities"
        assert len(result.entries) == 0
        assert "*No entries yet.*" in result.markdown

    @pytest.mark.asyncio
    async def test_get_file_with_entries(self):
        rows = [
            _make_db_row(title="Capability A", content="Can do A"),
            _make_db_row(title="Capability B", content="Can do B"),
        ]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.get_file(KnowledgeCategory.CAPABILITIES)

        assert len(result.entries) == 2
        assert "Capability A" in result.markdown
        assert "Capability B" in result.markdown
        assert result.last_updated is not None

    @pytest.mark.asyncio
    async def test_get_user_file_without_user_id(self):
        mock_db = AsyncMock()
        km = KnowledgeManager(db=mock_db)
        result = await km.get_file(KnowledgeCategory.USER)

        assert "No user ID specified" in result.markdown
        assert len(result.entries) == 0

    @pytest.mark.asyncio
    async def test_get_user_file_with_user_id(self):
        rows = [
            _make_db_row(
                category="user",
                title="User pref",
                content="Prefers research",
                user_id="user-123",
                source="trust_tracker",
            ),
        ]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.get_file(KnowledgeCategory.USER, user_id="user-123")

        assert len(result.entries) == 1
        mock_db.list_knowledge_entries.assert_called_once_with(
            category="user", user_id="user-123"
        )


class TestKnowledgeManagerRendering:
    """Tests for markdown rendering."""

    @pytest.mark.asyncio
    async def test_renders_category_header(self):
        rows = [_make_db_row(title="Test", content="Content")]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.get_file(KnowledgeCategory.BOUNDARIES)

        assert result.markdown.startswith("# Boundaries")

    @pytest.mark.asyncio
    async def test_renders_confidence_marker(self):
        rows = [
            _make_db_row(
                title="Uncertain entry",
                content="Maybe works",
                confidence=0.6,
                source="error_tracker",
            ),
        ]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.get_file(KnowledgeCategory.PATTERNS)

        assert "confidence: 60%" in result.markdown

    @pytest.mark.asyncio
    async def test_groups_by_source(self):
        rows = [
            _make_db_row(title="Seed entry", source="seed"),
            _make_db_row(title="Learned entry", source="error_tracker"),
        ]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.get_file(KnowledgeCategory.PATTERNS)

        assert "## Seed" in result.markdown
        assert "## Error Tracker" in result.markdown


class TestKnowledgeManagerAddEntry:
    """Tests for manual entry creation."""

    @pytest.mark.asyncio
    async def test_add_entry(self):
        mock_db = AsyncMock()
        created_row = _make_db_row(
            category="patterns",
            title="New pattern",
            content="A new pattern",
            source="manual",
        )
        mock_db.create_knowledge_entry = AsyncMock(return_value=created_row)

        km = KnowledgeManager(db=mock_db)
        create = KnowledgeEntryCreate(
            category=KnowledgeCategory.PATTERNS,
            title="New pattern",
            content="A new pattern",
        )
        result = await km.add_entry(create)

        assert result.title == "New pattern"
        assert result.source == KnowledgeSource.MANUAL
        mock_db.create_knowledge_entry.assert_called_once()
        call_data = mock_db.create_knowledge_entry.call_args[0][0]
        assert call_data["source"] == "manual"

    @pytest.mark.asyncio
    async def test_add_user_entry(self):
        mock_db = AsyncMock()
        created_row = _make_db_row(
            category="user",
            title="User pref",
            content="Content",
            source="manual",
            user_id="user-abc",
        )
        mock_db.create_knowledge_entry = AsyncMock(return_value=created_row)

        km = KnowledgeManager(db=mock_db)
        create = KnowledgeEntryCreate(
            category=KnowledgeCategory.USER,
            title="User pref",
            content="Content",
            user_id="user-abc",
        )
        result = await km.add_entry(create)
        assert result.user_id == "user-abc"


class TestKnowledgeManagerListEntries:
    """Tests for entry listing."""

    @pytest.mark.asyncio
    async def test_list_all(self):
        rows = [_make_db_row(), _make_db_row()]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.list_entries()

        assert len(result) == 2
        mock_db.list_knowledge_entries.assert_called_once_with(
            category=None, source=None
        )

    @pytest.mark.asyncio
    async def test_list_filtered(self):
        rows = [_make_db_row(source="error_tracker")]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.list_entries(
            category="patterns", source="error_tracker"
        )

        assert len(result) == 1
        mock_db.list_knowledge_entries.assert_called_once_with(
            category="patterns", source="error_tracker"
        )


class TestKnowledgeManagerUserKnowledge:
    """Tests for per-user knowledge aggregation."""

    @pytest.mark.asyncio
    async def test_user_knowledge_no_tracker(self):
        rows = [
            _make_db_row(
                category="user",
                title="Pattern learned",
                content="User prefers research",
                user_id="user-123",
                source="manual",
            ),
        ]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.get_user_knowledge("user-123")

        assert result.user_id == "user-123"
        assert result.trust_level == 0
        assert len(result.entries) == 1
        assert "User Knowledge: user-123" in result.markdown

    @pytest.mark.asyncio
    async def test_user_knowledge_with_trust_tracker(self):
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=[])

        # Create mock trust tracker with metrics
        mock_trust = MagicMock()
        user_id = uuid4()
        app_id = uuid4()
        mock_metrics = MagicMock()
        mock_metrics.current_trust_level = 2
        mock_metrics.total_tasks = 50
        mock_metrics.success_rate = 0.92
        mock_metrics.consecutive_successes = 12
        mock_trust._metrics = {(app_id, user_id): mock_metrics}

        km = KnowledgeManager(db=mock_db, trust_tracker=mock_trust)
        result = await km.get_user_knowledge(str(user_id))

        assert result.trust_level == 2
        assert result.total_tasks == 50
        assert result.success_rate == 0.92
        assert "Trust Level:** 2" in result.markdown

    @pytest.mark.asyncio
    async def test_user_knowledge_extracts_patterns(self):
        rows = [
            _make_db_row(
                category="user",
                title="Pattern: research preferred",
                content="User prefers research",
                user_id="user-123",
            ),
            _make_db_row(
                category="user",
                title="General note",
                content="A general note",
                user_id="user-123",
            ),
        ]
        mock_db = AsyncMock()
        mock_db.list_knowledge_entries = AsyncMock(return_value=rows)

        km = KnowledgeManager(db=mock_db)
        result = await km.get_user_knowledge("user-123")

        # "Pattern: research preferred" should be in preferred_patterns
        assert len(result.preferred_patterns) == 1
        assert "Pattern: research preferred" in result.preferred_patterns


# =============================================================================
# Refresh from Trackers Tests
# =============================================================================


class TestKnowledgeManagerRefreshErrors:
    """Tests for refresh from error tracker."""

    @pytest.mark.asyncio
    async def test_refresh_no_trackers(self):
        mock_db = AsyncMock()
        km = KnowledgeManager(db=mock_db)

        result = await km.refresh_from_trackers()

        assert result.entries_created == 0
        assert result.sources_refreshed == []

    @pytest.mark.asyncio
    async def test_refresh_from_error_tracker(self):
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        # Create a mock error tracker with patterns
        mock_error_tracker = MagicMock()
        mock_pattern = MagicMock()
        mock_pattern.name = "timeout_api"
        mock_pattern.description = "API timeouts are common"
        mock_pattern.occurrence_count = 7
        mock_pattern.confidence = 0.8
        mock_pattern.suggested_action = "Increase timeout to 30s"
        mock_error_tracker.get_patterns.return_value = [mock_pattern]

        mock_stats = MagicMock()
        mock_stats.total_errors = 15
        mock_stats.recovery_rate = 0.6
        mock_stats.by_category = {"timeout": 7, "api_failure": 8}
        mock_error_tracker.get_stats.return_value = mock_stats

        km = KnowledgeManager(db=mock_db, error_tracker=mock_error_tracker)
        result = await km.refresh_from_trackers()

        assert result.entries_created > 0
        assert "error_tracker" in result.sources_refreshed
        # Should create: 1 boundary + 1 pattern (for the pattern) + 1 stats summary
        assert result.entries_created == 3

    @pytest.mark.asyncio
    async def test_refresh_error_tracker_low_occurrence(self):
        """Patterns with < 5 occurrences don't become boundaries."""
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        mock_error_tracker = MagicMock()
        mock_pattern = MagicMock()
        mock_pattern.name = "rare_error"
        mock_pattern.description = "Rare error"
        mock_pattern.occurrence_count = 3  # Below boundary threshold
        mock_pattern.confidence = 0.5
        mock_pattern.suggested_action = None
        mock_error_tracker.get_patterns.return_value = [mock_pattern]

        mock_stats = MagicMock()
        mock_stats.total_errors = 3
        mock_stats.recovery_rate = 0.0
        mock_stats.by_category = {"timeout": 3}
        mock_error_tracker.get_stats.return_value = mock_stats

        km = KnowledgeManager(db=mock_db, error_tracker=mock_error_tracker)
        result = await km.refresh_from_trackers()

        # Should create: 1 pattern (no boundary since < 5) + 1 stats
        assert result.entries_created == 2


class TestKnowledgeManagerRefreshArrangements:
    """Tests for refresh from arrangement tracker."""

    @pytest.mark.asyncio
    async def test_refresh_from_arrangement_tracker(self):
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        mock_arr_tracker = MagicMock()

        # Mock execution data
        mock_exec1 = MagicMock()
        mock_exec1.outcome = "complete"
        mock_exec1.confidence = 0.9
        mock_exec2 = MagicMock()
        mock_exec2.outcome = "complete"
        mock_exec2.confidence = 0.85
        mock_exec3 = MagicMock()
        mock_exec3.outcome = "bounded"
        mock_exec3.confidence = 0.5

        mock_arrangement = MagicMock()
        mock_arrangement.name = "research-then-synthesize"

        mock_arr_tracker._executions = {"abc123": [mock_exec1, mock_exec2, mock_exec3]}
        mock_arr_tracker._arrangements = {"abc123": mock_arrangement}
        mock_arr_tracker._saved = {}

        km = KnowledgeManager(db=mock_db, arrangement_tracker=mock_arr_tracker)
        result = await km.refresh_from_trackers()

        assert result.entries_created > 0
        assert "arrangement_tracker" in result.sources_refreshed

    @pytest.mark.asyncio
    async def test_refresh_skips_single_execution(self):
        """Arrangements with only 1 execution are skipped."""
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        mock_arr_tracker = MagicMock()
        mock_exec = MagicMock()
        mock_exec.outcome = "complete"
        mock_exec.confidence = 0.9

        mock_arr_tracker._executions = {"abc": [mock_exec]}
        mock_arr_tracker._arrangements = {"abc": MagicMock(name="solo")}
        mock_arr_tracker._saved = {}

        km = KnowledgeManager(db=mock_db, arrangement_tracker=mock_arr_tracker)
        result = await km.refresh_from_trackers()

        # Single execution → no entries
        assert result.entries_created == 0

    @pytest.mark.asyncio
    async def test_refresh_includes_saved_arrangements(self):
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        mock_arr_tracker = MagicMock()
        mock_arr_tracker._executions = {}
        mock_arr_tracker._arrangements = {}

        mock_saved = MagicMock()
        mock_saved.name = "weekly-research"
        mock_saved.description = "Weekly research pipeline"
        mock_saved.composition_type = "sequential"
        mock_arr_tracker._saved = {"saved1": mock_saved}

        km = KnowledgeManager(db=mock_db, arrangement_tracker=mock_arr_tracker)
        result = await km.refresh_from_trackers()

        # 1 entry for the saved arrangement
        assert result.entries_created == 1


class TestKnowledgeManagerRefreshTrust:
    """Tests for refresh from trust tracker."""

    @pytest.mark.asyncio
    async def test_refresh_from_trust_tracker(self):
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        mock_trust = MagicMock()
        user_id = uuid4()
        app_id = uuid4()
        mock_metrics = MagicMock()
        mock_metrics.current_trust_level = 1
        mock_metrics.total_tasks = 20
        mock_metrics.success_rate = 0.85
        mock_metrics.consecutive_successes = 8
        mock_trust._metrics = {(app_id, user_id): mock_metrics}

        km = KnowledgeManager(db=mock_db, trust_tracker=mock_trust)
        result = await km.refresh_from_trackers()

        assert result.entries_created == 1
        assert "trust_tracker" in result.sources_refreshed

    @pytest.mark.asyncio
    async def test_refresh_trust_skips_app_only(self):
        """App-level metrics (user_id=None) are skipped."""
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        mock_trust = MagicMock()
        app_id = uuid4()
        mock_metrics = MagicMock()
        mock_metrics.total_tasks = 10
        mock_trust._metrics = {(app_id, None): mock_metrics}

        km = KnowledgeManager(db=mock_db, trust_tracker=mock_trust)
        result = await km.refresh_from_trackers()

        assert result.entries_created == 0

    @pytest.mark.asyncio
    async def test_refresh_trust_skips_zero_tasks(self):
        """Users with 0 tasks are skipped."""
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=0)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        mock_trust = MagicMock()
        user_id = uuid4()
        app_id = uuid4()
        mock_metrics = MagicMock()
        mock_metrics.total_tasks = 0
        mock_trust._metrics = {(app_id, user_id): mock_metrics}

        km = KnowledgeManager(db=mock_db, trust_tracker=mock_trust)
        result = await km.refresh_from_trackers()

        assert result.entries_created == 0


class TestKnowledgeManagerReplaceEntries:
    """Tests for the replace-on-refresh behavior."""

    @pytest.mark.asyncio
    async def test_refresh_removes_old_entries(self):
        mock_db = AsyncMock()
        mock_db.delete_knowledge_entries_by_source = AsyncMock(return_value=2)
        mock_db.create_knowledge_entry = AsyncMock(return_value={"id": str(uuid4())})

        # Error tracker with 1 pattern
        mock_error_tracker = MagicMock()
        mock_pattern = MagicMock()
        mock_pattern.name = "test"
        mock_pattern.description = "Test pattern"
        mock_pattern.occurrence_count = 3
        mock_pattern.confidence = 0.5
        mock_pattern.suggested_action = None
        mock_error_tracker.get_patterns.return_value = [mock_pattern]

        mock_stats = MagicMock()
        mock_stats.total_errors = 3
        mock_stats.recovery_rate = 0.0
        mock_stats.by_category = {"timeout": 3}
        mock_error_tracker.get_stats.return_value = mock_stats

        km = KnowledgeManager(db=mock_db, error_tracker=mock_error_tracker)
        result = await km.refresh_from_trackers()

        assert result.entries_removed > 0
        # delete_knowledge_entries_by_source should be called for each category
        assert mock_db.delete_knowledge_entries_by_source.call_count > 0


# =============================================================================
# API Endpoint Tests (via route functions)
# =============================================================================


class TestKnowledgeEndpoints:
    """Tests for knowledge API endpoints."""

    @pytest.mark.asyncio
    async def test_get_capabilities_endpoint(self):
        """Test GET /knowledge/capabilities route function."""
        from loop_symphony.api.routes import get_capabilities_knowledge

        mock_km = AsyncMock(spec=KnowledgeManager)
        mock_km.get_file = AsyncMock(return_value=KnowledgeFile(
            category=KnowledgeCategory.CAPABILITIES,
            title="Capabilities",
            markdown="# Capabilities\n\nTest",
            entries=[],
        ))

        result = await get_capabilities_knowledge(km=mock_km)

        assert result.category == KnowledgeCategory.CAPABILITIES
        mock_km.get_file.assert_called_once_with(KnowledgeCategory.CAPABILITIES)

    @pytest.mark.asyncio
    async def test_get_boundaries_endpoint(self):
        from loop_symphony.api.routes import get_boundaries_knowledge

        mock_km = AsyncMock(spec=KnowledgeManager)
        mock_km.get_file = AsyncMock(return_value=KnowledgeFile(
            category=KnowledgeCategory.BOUNDARIES,
            title="Boundaries",
            markdown="# Boundaries",
            entries=[],
        ))

        result = await get_boundaries_knowledge(km=mock_km)
        mock_km.get_file.assert_called_once_with(KnowledgeCategory.BOUNDARIES)

    @pytest.mark.asyncio
    async def test_get_user_knowledge_endpoint(self):
        from loop_symphony.api.routes import get_user_knowledge

        mock_km = AsyncMock(spec=KnowledgeManager)
        mock_km.get_user_knowledge = AsyncMock(return_value=UserKnowledge(
            user_id="user-123",
            trust_level=1,
            total_tasks=10,
            success_rate=0.9,
        ))

        result = await get_user_knowledge(user_id="user-123", km=mock_km)

        assert result.user_id == "user-123"
        mock_km.get_user_knowledge.assert_called_once_with("user-123")

    @pytest.mark.asyncio
    async def test_create_entry_endpoint(self):
        from loop_symphony.api.routes import create_knowledge_entry

        mock_km = AsyncMock(spec=KnowledgeManager)
        entry = KnowledgeEntry(
            category=KnowledgeCategory.PATTERNS,
            title="New",
            content="New pattern",
            source=KnowledgeSource.MANUAL,
        )
        mock_km.add_entry = AsyncMock(return_value=entry)

        create_req = KnowledgeEntryCreate(
            category=KnowledgeCategory.PATTERNS,
            title="New",
            content="New pattern",
        )
        result = await create_knowledge_entry(entry=create_req, km=mock_km)

        assert result["title"] == "New"
        mock_km.add_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_entries_endpoint(self):
        from loop_symphony.api.routes import list_knowledge_entries

        mock_km = AsyncMock(spec=KnowledgeManager)
        mock_km.list_entries = AsyncMock(return_value=[
            KnowledgeEntry(
                category=KnowledgeCategory.PATTERNS,
                title="Entry 1",
                content="Content 1",
            ),
        ])

        result = await list_knowledge_entries(
            km=mock_km, category="patterns", source=None
        )

        assert len(result) == 1
        mock_km.list_entries.assert_called_once_with(
            category="patterns", source=None
        )

    @pytest.mark.asyncio
    async def test_refresh_endpoint(self):
        from loop_symphony.api.routes import refresh_knowledge

        mock_km = AsyncMock(spec=KnowledgeManager)
        mock_km.refresh_from_trackers = AsyncMock(
            return_value=KnowledgeRefreshResult(
                entries_created=5,
                entries_removed=2,
                sources_refreshed=["error_tracker"],
            )
        )

        result = await refresh_knowledge(km=mock_km)

        assert result.entries_created == 5
        assert result.entries_removed == 2

    @pytest.mark.asyncio
    async def test_get_changelog_endpoint(self):
        from loop_symphony.api.routes import get_changelog_knowledge

        mock_km = AsyncMock(spec=KnowledgeManager)
        mock_km.get_file = AsyncMock(return_value=KnowledgeFile(
            category=KnowledgeCategory.CHANGELOG,
            title="Changelog",
            markdown="# Changelog",
            entries=[],
        ))

        result = await get_changelog_knowledge(km=mock_km)
        mock_km.get_file.assert_called_once_with(KnowledgeCategory.CHANGELOG)

    @pytest.mark.asyncio
    async def test_get_patterns_endpoint(self):
        from loop_symphony.api.routes import get_patterns_knowledge

        mock_km = AsyncMock(spec=KnowledgeManager)
        mock_km.get_file = AsyncMock(return_value=KnowledgeFile(
            category=KnowledgeCategory.PATTERNS,
            title="Patterns",
            markdown="# Patterns",
            entries=[],
        ))

        result = await get_patterns_knowledge(km=mock_km)
        mock_km.get_file.assert_called_once_with(KnowledgeCategory.PATTERNS)


# =============================================================================
# DB Client Method Tests
# =============================================================================


class TestDatabaseClientKnowledge:
    """Tests for DatabaseClient knowledge methods."""

    @pytest.mark.asyncio
    async def test_create_knowledge_entry(self):
        from loop_symphony.db.client import DatabaseClient

        with patch.object(DatabaseClient, "__init__", lambda self: None):
            db = DatabaseClient()
            mock_table = MagicMock()
            mock_table.insert.return_value.execute.return_value.data = [
                {"id": "test-id", "title": "Test"}
            ]
            db.client = MagicMock()
            db.client.table.return_value = mock_table

            result = await db.create_knowledge_entry({"title": "Test"})
            assert result["title"] == "Test"
            db.client.table.assert_called_with("knowledge_entries")

    @pytest.mark.asyncio
    async def test_list_knowledge_entries_filtered(self):
        from loop_symphony.db.client import DatabaseClient

        with patch.object(DatabaseClient, "__init__", lambda self: None):
            db = DatabaseClient()
            mock_chain = MagicMock()
            mock_chain.select.return_value = mock_chain
            mock_chain.eq.return_value = mock_chain
            mock_chain.order.return_value = mock_chain
            mock_chain.execute.return_value.data = [{"id": "1"}, {"id": "2"}]
            db.client = MagicMock()
            db.client.table.return_value = mock_chain

            result = await db.list_knowledge_entries(
                category="capabilities", source="seed"
            )
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_delete_knowledge_entry_soft(self):
        from loop_symphony.db.client import DatabaseClient

        with patch.object(DatabaseClient, "__init__", lambda self: None):
            db = DatabaseClient()
            mock_chain = MagicMock()
            mock_chain.update.return_value = mock_chain
            mock_chain.eq.return_value = mock_chain
            mock_chain.execute.return_value.data = [{"id": "test-id"}]
            db.client = MagicMock()
            db.client.table.return_value = mock_chain

            result = await db.delete_knowledge_entry("test-id")
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_entries_by_source(self):
        from loop_symphony.db.client import DatabaseClient

        with patch.object(DatabaseClient, "__init__", lambda self: None):
            db = DatabaseClient()
            mock_chain = MagicMock()
            mock_chain.update.return_value = mock_chain
            mock_chain.eq.return_value = mock_chain
            mock_chain.execute.return_value.data = [{"id": "1"}, {"id": "2"}]
            db.client = MagicMock()
            db.client.table.return_value = mock_chain

            result = await db.delete_knowledge_entries_by_source(
                category="patterns", source="error_tracker"
            )
            assert result == 2
