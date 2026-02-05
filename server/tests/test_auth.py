"""Tests for authentication middleware."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from loop_symphony.api import auth
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
def mock_inactive_app() -> App:
    """Create a mock inactive App for testing."""
    return App(
        id=uuid4(),
        name="inactive-app",
        api_key="inactive-api-key-12345",
        description="Inactive application",
        is_active=False,
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
        preferences={"theme": "dark"},
        created_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_db():
    """Create a mock DatabaseClient."""
    return MagicMock()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons between tests."""
    auth._db_client = None
    yield
    auth._db_client = None


# ---------------------------------------------------------------------------
# TestGetAppFromApiKey
# ---------------------------------------------------------------------------

class TestGetAppFromApiKey:
    """Tests for get_app_from_api_key dependency."""

    @pytest.mark.asyncio
    async def test_valid_api_key_returns_app(self, mock_db, mock_app):
        """Valid API key returns the associated App."""
        mock_db.get_app_by_api_key = AsyncMock(return_value=mock_app)

        result = await auth.get_app_from_api_key("test-api-key-12345", mock_db)

        assert result == mock_app
        mock_db.get_app_by_api_key.assert_called_once_with("test-api-key-12345")

    @pytest.mark.asyncio
    async def test_invalid_api_key_raises_401(self, mock_db):
        """Invalid API key raises 401 Unauthorized."""
        mock_db.get_app_by_api_key = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await auth.get_app_from_api_key("invalid-key", mock_db)

        assert exc_info.value.status_code == 401
        assert "Invalid API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_inactive_app_raises_403(self, mock_db, mock_inactive_app):
        """Inactive app raises 403 Forbidden."""
        mock_db.get_app_by_api_key = AsyncMock(return_value=mock_inactive_app)

        with pytest.raises(HTTPException) as exc_info:
            await auth.get_app_from_api_key("inactive-api-key-12345", mock_db)

        assert exc_info.value.status_code == 403
        assert "deactivated" in exc_info.value.detail


# ---------------------------------------------------------------------------
# TestGetAuthContext
# ---------------------------------------------------------------------------

class TestGetAuthContext:
    """Tests for get_auth_context dependency."""

    @pytest.mark.asyncio
    async def test_returns_auth_context_with_app_only(self, mock_db, mock_app):
        """Returns AuthContext with just app when no user ID provided."""
        result = await auth.get_auth_context(mock_app, mock_db, x_user_id=None)

        assert isinstance(result, AuthContext)
        assert result.app == mock_app
        assert result.user is None

    @pytest.mark.asyncio
    async def test_returns_auth_context_with_user(self, mock_db, mock_app, mock_user):
        """Returns AuthContext with user when user ID provided."""
        mock_db.get_or_create_user_profile = AsyncMock(return_value=mock_user)
        mock_db.update_user_last_seen = AsyncMock()

        result = await auth.get_auth_context(mock_app, mock_db, x_user_id="device-123")

        assert isinstance(result, AuthContext)
        assert result.app == mock_app
        assert result.user == mock_user
        mock_db.get_or_create_user_profile.assert_called_once_with(
            mock_app.id, "device-123"
        )
        mock_db.update_user_last_seen.assert_called_once_with(mock_user.id)

    @pytest.mark.asyncio
    async def test_creates_new_user_profile_if_not_exists(self, mock_db, mock_app):
        """Creates new user profile if external_user_id doesn't exist."""
        new_user = UserProfile(
            id=uuid4(),
            app_id=mock_app.id,
            external_user_id="new-device",
            display_name=None,
            preferences={},
            created_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
        mock_db.get_or_create_user_profile = AsyncMock(return_value=new_user)
        mock_db.update_user_last_seen = AsyncMock()

        result = await auth.get_auth_context(mock_app, mock_db, x_user_id="new-device")

        assert result.user == new_user
        assert result.user.external_user_id == "new-device"


# ---------------------------------------------------------------------------
# TestGetOptionalAuthContext
# ---------------------------------------------------------------------------

class TestGetOptionalAuthContext:
    """Tests for get_optional_auth_context dependency."""

    @pytest.mark.asyncio
    async def test_returns_none_without_api_key(self, mock_db):
        """Returns None when no API key provided."""
        result = await auth.get_optional_auth_context(mock_db, x_api_key=None)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_api_key(self, mock_db):
        """Returns None for invalid API key (no exception)."""
        mock_db.get_app_by_api_key = AsyncMock(return_value=None)

        result = await auth.get_optional_auth_context(
            mock_db, x_api_key="invalid-key"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_inactive_app(self, mock_db, mock_inactive_app):
        """Returns None for inactive app (no exception)."""
        mock_db.get_app_by_api_key = AsyncMock(return_value=mock_inactive_app)

        result = await auth.get_optional_auth_context(
            mock_db, x_api_key="inactive-api-key-12345"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_auth_context_for_valid_key(self, mock_db, mock_app):
        """Returns AuthContext for valid API key."""
        mock_db.get_app_by_api_key = AsyncMock(return_value=mock_app)

        result = await auth.get_optional_auth_context(
            mock_db, x_api_key="test-api-key-12345"
        )

        assert isinstance(result, AuthContext)
        assert result.app == mock_app
        assert result.user is None

    @pytest.mark.asyncio
    async def test_returns_auth_context_with_user(
        self, mock_db, mock_app, mock_user
    ):
        """Returns AuthContext with user when both API key and user ID provided."""
        mock_db.get_app_by_api_key = AsyncMock(return_value=mock_app)
        mock_db.get_or_create_user_profile = AsyncMock(return_value=mock_user)
        mock_db.update_user_last_seen = AsyncMock()

        result = await auth.get_optional_auth_context(
            mock_db, x_api_key="test-api-key-12345", x_user_id="device-123"
        )

        assert result.app == mock_app
        assert result.user == mock_user


# ---------------------------------------------------------------------------
# TestAuthContextModel
# ---------------------------------------------------------------------------

class TestAuthContextModel:
    """Tests for AuthContext model."""

    def test_auth_context_app_required(self, mock_app):
        """AuthContext requires an app."""
        ctx = AuthContext(app=mock_app)
        assert ctx.app == mock_app
        assert ctx.user is None

    def test_auth_context_with_user(self, mock_app, mock_user):
        """AuthContext can include a user."""
        ctx = AuthContext(app=mock_app, user=mock_user)
        assert ctx.app == mock_app
        assert ctx.user == mock_user
