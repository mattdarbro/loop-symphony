"""Configuration for Local Room."""

import os
from pydantic import BaseModel, Field


class LocalRoomConfig(BaseModel):
    """Configuration for the Local Room service."""

    # Room identity
    room_id: str = Field(default="local-room-1")
    room_name: str = Field(default="Local Room")

    # Server connection
    server_url: str = Field(default="http://localhost:8000")
    registration_interval: int = Field(default=60)  # Seconds between heartbeats

    # Ollama settings
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.2")  # Default model
    ollama_timeout: int = Field(default=120)  # Seconds

    # Local API
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8001)

    # Capabilities
    capabilities: set[str] = Field(default_factory=lambda: {"reasoning"})

    @classmethod
    def from_env(cls) -> "LocalRoomConfig":
        """Load configuration from environment variables."""
        return cls(
            room_id=os.getenv("LOCAL_ROOM_ID", "local-room-1"),
            room_name=os.getenv("LOCAL_ROOM_NAME", "Local Room"),
            server_url=os.getenv("LOOP_SYMPHONY_SERVER_URL", "http://localhost:8000"),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            host=os.getenv("LOCAL_ROOM_HOST", "0.0.0.0"),
            port=int(os.getenv("LOCAL_ROOM_PORT", "8001")),
        )
