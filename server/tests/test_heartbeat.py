"""Tests for heartbeat endpoints and models."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from loop_symphony.api import routes
from loop_symphony.models.heartbeat import (
    Heartbeat,
    HeartbeatCreate,
    HeartbeatRun,
    HeartbeatStatus,
    HeartbeatUpdate,
)
from loop_symphony.models.identity import App, AuthContext, UserProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_app() -> App:
    """Create a mock App for testing."""
    return App(
        id=uuid4(),
        name="test-app",
        api_key="test-api-key-12345",
        description="Test application",
        is_active=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_user(mock_app: App) -> UserProfile:
    """Create a mock UserProfile for testing."""
    return UserProfile(
        id=uuid4(),
        app_id=mock_app.id,
        external_user_id="device-123",
        display_name="Test User",
        preferences={},
        created_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_auth_context(mock_app: App, mock_user: UserProfile) -> AuthContext:
    """Create a mock AuthContext for testing."""
    return AuthContext(app=mock_app, user=mock_user)


@pytest.fixture
def mock_auth_context_no_user(mock_app: App) -> AuthContext:
    """Create a mock AuthContext without user."""
    return AuthContext(app=mock_app, user=None)


@pytest.fixture
def mock_heartbeat(mock_app: App, mock_user: UserProfile) -> Heartbeat:
    """Create a mock Heartbeat for testing."""
    return Heartbeat(
        id=uuid4(),
        app_id=mock_app.id,
        user_id=mock_user.id,
        name="Daily Briefing",
        query_template="Give me a daily briefing for {date}",
        cron_expression="0 7 * * *",
        timezone="America/Chicago",
        is_active=True,
        context_template={"type": "briefing"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_db():
    """Create a mock DatabaseClient."""
    return MagicMock()


# ---------------------------------------------------------------------------
# TestHeartbeatModels
# ---------------------------------------------------------------------------

class TestHeartbeatModels:
    """Tests for heartbeat Pydantic models."""

    def test_heartbeat_status_enum(self):
        """HeartbeatStatus has expected values."""
        assert HeartbeatStatus.PENDING == "pending"
        assert HeartbeatStatus.RUNNING == "running"
        assert HeartbeatStatus.COMPLETED == "completed"
        assert HeartbeatStatus.FAILED == "failed"

    def test_heartbeat_create_minimal(self):
        """HeartbeatCreate works with minimal required fields."""
        data = HeartbeatCreate(
            name="Test",
            query_template="What is {date}?",
            cron_expression="0 * * * *",
        )
        assert data.name == "Test"
        assert data.timezone == "UTC"  # default
        assert data.context_template == {}  # default

    def test_heartbeat_create_full(self):
        """HeartbeatCreate works with all fields."""
        data = HeartbeatCreate(
            name="Full Test",
            query_template="Process {date} for {user}",
            cron_expression="0 7 * * 1-5",
            timezone="America/New_York",
            context_template={"priority": "high"},
        )
        assert data.name == "Full Test"
        assert data.timezone == "America/New_York"
        assert data.context_template == {"priority": "high"}

    def test_heartbeat_update_partial(self):
        """HeartbeatUpdate allows partial updates."""
        update = HeartbeatUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.query_template is None
        assert update.is_active is None

    def test_heartbeat_update_exclude_none(self):
        """HeartbeatUpdate.model_dump(exclude_none=True) removes unset fields."""
        update = HeartbeatUpdate(name="New Name", is_active=False)
        dumped = update.model_dump(exclude_none=True)
        assert dumped == {"name": "New Name", "is_active": False}

    def test_heartbeat_model_complete(self, mock_app, mock_user):
        """Heartbeat model works with all fields."""
        hb = Heartbeat(
            id=uuid4(),
            app_id=mock_app.id,
            user_id=mock_user.id,
            name="Test",
            query_template="Test query",
            cron_expression="* * * * *",
            timezone="UTC",
            is_active=True,
            context_template={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert hb.name == "Test"
        assert hb.user_id == mock_user.id

    def test_heartbeat_model_no_user(self, mock_app):
        """Heartbeat model works without user (app-wide heartbeat)."""
        hb = Heartbeat(
            id=uuid4(),
            app_id=mock_app.id,
            user_id=None,
            name="App-wide",
            query_template="System check",
            cron_expression="0 0 * * *",
            timezone="UTC",
            is_active=True,
            context_template={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert hb.user_id is None

    def test_heartbeat_run_model(self, mock_heartbeat):
        """HeartbeatRun model works correctly."""
        run = HeartbeatRun(
            id=uuid4(),
            heartbeat_id=mock_heartbeat.id,
            task_id=None,
            status=HeartbeatStatus.PENDING,
            started_at=None,
            completed_at=None,
            error_message=None,
            created_at=datetime.now(UTC),
        )
        assert run.status == HeartbeatStatus.PENDING
        assert run.task_id is None


# ---------------------------------------------------------------------------
# TestHeartbeatEndpoints
# ---------------------------------------------------------------------------

class TestCreateHeartbeatEndpoint:
    """Tests for create_heartbeat endpoint."""

    @pytest.mark.asyncio
    async def test_creates_heartbeat_with_user(
        self, mock_db, mock_auth_context, mock_heartbeat
    ):
        """Creates heartbeat with user ID when user provided."""
        mock_db.create_heartbeat = AsyncMock(return_value=mock_heartbeat)

        data = HeartbeatCreate(
            name="Daily Briefing",
            query_template="Give me a daily briefing for {date}",
            cron_expression="0 7 * * *",
        )

        result = await routes.create_heartbeat(data, mock_auth_context, mock_db)

        assert result == mock_heartbeat
        mock_db.create_heartbeat.assert_called_once_with(
            mock_auth_context.app.id,
            mock_auth_context.user.id,
            data,
        )

    @pytest.mark.asyncio
    async def test_creates_heartbeat_without_user(
        self, mock_db, mock_auth_context_no_user, mock_app
    ):
        """Creates app-wide heartbeat when no user."""
        app_wide_heartbeat = Heartbeat(
            id=uuid4(),
            app_id=mock_app.id,
            user_id=None,
            name="System Check",
            query_template="Run system check",
            cron_expression="0 0 * * *",
            timezone="UTC",
            is_active=True,
            context_template={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_db.create_heartbeat = AsyncMock(return_value=app_wide_heartbeat)

        data = HeartbeatCreate(
            name="System Check",
            query_template="Run system check",
            cron_expression="0 0 * * *",
        )

        result = await routes.create_heartbeat(
            data, mock_auth_context_no_user, mock_db
        )

        assert result.user_id is None
        mock_db.create_heartbeat.assert_called_once_with(
            mock_auth_context_no_user.app.id,
            None,
            data,
        )


class TestListHeartbeatsEndpoint:
    """Tests for list_heartbeats endpoint."""

    @pytest.mark.asyncio
    async def test_lists_heartbeats(
        self, mock_db, mock_auth_context, mock_heartbeat
    ):
        """Lists heartbeats for authenticated app/user."""
        mock_db.list_heartbeats = AsyncMock(return_value=[mock_heartbeat])

        result = await routes.list_heartbeats(mock_auth_context, mock_db)

        assert result == [mock_heartbeat]
        mock_db.list_heartbeats.assert_called_once_with(
            mock_auth_context.app.id,
            mock_auth_context.user.id,
        )

    @pytest.mark.asyncio
    async def test_lists_empty_heartbeats(self, mock_db, mock_auth_context):
        """Returns empty list when no heartbeats exist."""
        mock_db.list_heartbeats = AsyncMock(return_value=[])

        result = await routes.list_heartbeats(mock_auth_context, mock_db)

        assert result == []


class TestGetHeartbeatEndpoint:
    """Tests for get_heartbeat endpoint."""

    @pytest.mark.asyncio
    async def test_returns_heartbeat(
        self, mock_db, mock_auth_context, mock_heartbeat
    ):
        """Returns heartbeat when found."""
        mock_db.get_heartbeat = AsyncMock(return_value=mock_heartbeat)

        result = await routes.get_heartbeat(
            mock_heartbeat.id, mock_auth_context, mock_db
        )

        assert result == mock_heartbeat

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self, mock_db, mock_auth_context):
        """Raises 404 when heartbeat not found."""
        mock_db.get_heartbeat = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await routes.get_heartbeat(uuid4(), mock_auth_context, mock_db)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail


class TestUpdateHeartbeatEndpoint:
    """Tests for update_heartbeat endpoint."""

    @pytest.mark.asyncio
    async def test_updates_heartbeat(
        self, mock_db, mock_auth_context, mock_heartbeat
    ):
        """Updates heartbeat when found."""
        updated_heartbeat = mock_heartbeat.model_copy(
            update={"name": "Updated Name"}
        )
        mock_db.update_heartbeat = AsyncMock(return_value=updated_heartbeat)

        updates = HeartbeatUpdate(name="Updated Name")
        result = await routes.update_heartbeat(
            mock_heartbeat.id, updates, mock_auth_context, mock_db
        )

        assert result.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self, mock_db, mock_auth_context):
        """Raises 404 when heartbeat not found."""
        mock_db.update_heartbeat = AsyncMock(return_value=None)

        updates = HeartbeatUpdate(name="New Name")
        with pytest.raises(HTTPException) as exc_info:
            await routes.update_heartbeat(
                uuid4(), updates, mock_auth_context, mock_db
            )

        assert exc_info.value.status_code == 404


class TestDeleteHeartbeatEndpoint:
    """Tests for delete_heartbeat endpoint."""

    @pytest.mark.asyncio
    async def test_deletes_heartbeat(
        self, mock_db, mock_auth_context, mock_heartbeat
    ):
        """Deletes heartbeat when found."""
        mock_db.delete_heartbeat = AsyncMock(return_value=True)

        # Should not raise
        await routes.delete_heartbeat(
            mock_heartbeat.id, mock_auth_context, mock_db
        )

        mock_db.delete_heartbeat.assert_called_once_with(
            mock_heartbeat.id, mock_auth_context.app.id
        )

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self, mock_db, mock_auth_context):
        """Raises 404 when heartbeat not found."""
        mock_db.delete_heartbeat = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await routes.delete_heartbeat(uuid4(), mock_auth_context, mock_db)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# TestHeartbeatIsolation
# ---------------------------------------------------------------------------

class TestHeartbeatIsolation:
    """Tests for app isolation in heartbeat operations."""

    @pytest.mark.asyncio
    async def test_get_enforces_app_id(self, mock_db, mock_auth_context):
        """get_heartbeat passes app_id for isolation check."""
        mock_db.get_heartbeat = AsyncMock(return_value=None)
        heartbeat_id = uuid4()

        with pytest.raises(HTTPException):
            await routes.get_heartbeat(heartbeat_id, mock_auth_context, mock_db)

        mock_db.get_heartbeat.assert_called_once_with(
            heartbeat_id, mock_auth_context.app.id
        )

    @pytest.mark.asyncio
    async def test_update_enforces_app_id(self, mock_db, mock_auth_context):
        """update_heartbeat passes app_id for isolation check."""
        mock_db.update_heartbeat = AsyncMock(return_value=None)
        heartbeat_id = uuid4()
        updates = HeartbeatUpdate(name="New")

        with pytest.raises(HTTPException):
            await routes.update_heartbeat(
                heartbeat_id, updates, mock_auth_context, mock_db
            )

        mock_db.update_heartbeat.assert_called_once()
        call_args = mock_db.update_heartbeat.call_args
        assert call_args[0][1] == mock_auth_context.app.id

    @pytest.mark.asyncio
    async def test_delete_enforces_app_id(self, mock_db, mock_auth_context):
        """delete_heartbeat passes app_id for isolation check."""
        mock_db.delete_heartbeat = AsyncMock(return_value=False)
        heartbeat_id = uuid4()

        with pytest.raises(HTTPException):
            await routes.delete_heartbeat(
                heartbeat_id, mock_auth_context, mock_db
            )

        mock_db.delete_heartbeat.assert_called_once_with(
            heartbeat_id, mock_auth_context.app.id
        )
