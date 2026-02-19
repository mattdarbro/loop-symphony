"""Global test configuration for Loop Symphony."""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _set_test_env_vars():
    """Set dummy environment variables for Settings validation.

    This ensures tests don't require a real .env file or exported env vars.
    Only sets values that aren't already present, so real env vars take
    precedence (useful for integration tests).
    """
    defaults = {
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "TAVILY_API_KEY": "test-tavily-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_KEY": "test-supabase-key",
    }
    originals = {}
    for key, value in defaults.items():
        if key not in os.environ:
            os.environ[key] = value
            originals[key] = None
        else:
            originals[key] = os.environ[key]

    # Clear the lru_cache on get_settings so it picks up the new env vars
    from loop_symphony.config import get_settings
    get_settings.cache_clear()

    yield

    # Restore original env state
    for key, original in originals.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original
    get_settings.cache_clear()
