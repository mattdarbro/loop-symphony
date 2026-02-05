"""API authentication middleware."""

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from loop_symphony.db.client import DatabaseClient
from loop_symphony.models.identity import App, AuthContext, UserProfile

logger = logging.getLogger(__name__)

# Reuse the database client from routes
_db_client: DatabaseClient | None = None


def get_db_client() -> DatabaseClient:
    """Get or create database client instance."""
    global _db_client
    if _db_client is None:
        _db_client = DatabaseClient()
    return _db_client


async def get_app_from_api_key(
    x_api_key: Annotated[str, Header()],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
) -> App:
    """Validate API key and return associated app.

    Args:
        x_api_key: The API key from X-Api-Key header
        db: The database client

    Returns:
        The validated App

    Raises:
        HTTPException: If API key is invalid or app is deactivated
    """
    app = await db.get_app_by_api_key(x_api_key)

    if not app:
        logger.warning(f"Invalid API key attempted: {x_api_key[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if not app.is_active:
        logger.warning(f"Deactivated app access attempted: {app.name}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="App is deactivated",
        )

    return app


async def get_auth_context(
    app: Annotated[App, Depends(get_app_from_api_key)],
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> AuthContext:
    """Build full auth context with optional user.

    Args:
        app: The validated app
        db: The database client
        x_user_id: Optional user ID from X-User-Id header

    Returns:
        AuthContext with app and optional user
    """
    user: UserProfile | None = None

    if x_user_id:
        user = await db.get_or_create_user_profile(app.id, x_user_id)
        await db.update_user_last_seen(user.id)
        logger.debug(f"Auth context for app={app.name} user={x_user_id}")
    else:
        logger.debug(f"Auth context for app={app.name} (no user)")

    return AuthContext(app=app, user=user)


async def get_optional_auth_context(
    db: Annotated[DatabaseClient, Depends(get_db_client)],
    x_api_key: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
) -> AuthContext | None:
    """Build auth context if API key provided, otherwise return None.

    This is for endpoints that support both authenticated and anonymous access.

    Args:
        db: The database client
        x_api_key: Optional API key from X-Api-Key header
        x_user_id: Optional user ID from X-User-Id header

    Returns:
        AuthContext if API key provided and valid, None otherwise
    """
    if not x_api_key:
        return None

    app = await db.get_app_by_api_key(x_api_key)
    if not app or not app.is_active:
        return None

    user: UserProfile | None = None
    if x_user_id:
        user = await db.get_or_create_user_profile(app.id, x_user_id)
        await db.update_user_last_seen(user.id)

    return AuthContext(app=app, user=user)


# Type aliases for dependency injection
Auth = Annotated[AuthContext, Depends(get_auth_context)]
OptionalAuth = Annotated[AuthContext | None, Depends(get_optional_auth_context)]
AppOnly = Annotated[App, Depends(get_app_from_api_key)]
