"""Configuration and environment loading for Loop Symphony."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Anthropic
    anthropic_api_key: str

    # Tavily
    tavily_api_key: str

    # Supabase
    supabase_url: str
    supabase_key: str

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Claude model config
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 4096

    # Research instrument defaults
    research_max_iterations: int = 5
    research_confidence_threshold: float = 0.8
    research_confidence_delta_threshold: float = 0.05


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
