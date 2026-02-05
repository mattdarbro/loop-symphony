"""Identity models for multi-tenant support."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class App(BaseModel):
    """Registered application."""

    id: UUID
    name: str
    api_key: str
    description: str | None = None
    is_active: bool = True
    created_at: datetime


class UserProfile(BaseModel):
    """User profile within an app."""

    id: UUID
    app_id: UUID
    external_user_id: str
    display_name: str | None = None
    preferences: dict = Field(default_factory=dict)
    created_at: datetime
    last_seen_at: datetime


class AuthContext(BaseModel):
    """Authentication context for requests."""

    app: App
    user: UserProfile | None = None
