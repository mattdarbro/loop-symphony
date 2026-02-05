"""Tests for Tool protocol, ToolManifest, and protocol conformance."""

import dataclasses

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from loop_symphony.tools.base import Tool, ToolManifest
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.tools.tavily import TavilyClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_claude_settings():
    """Mock settings for ClaudeClient."""
    with patch("loop_symphony.tools.claude.get_settings") as mock:
        settings = MagicMock()
        settings.anthropic_api_key = "test-key"
        settings.claude_model = "test-model"
        settings.claude_max_tokens = 1024
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_tavily_settings():
    """Mock settings for TavilyClient."""
    with patch("loop_symphony.tools.tavily.get_settings") as mock:
        settings = MagicMock()
        settings.tavily_api_key = "test-key"
        mock.return_value = settings
        yield settings


@pytest.fixture
def claude_client(mock_claude_settings):
    """Create a ClaudeClient with mocked settings."""
    with patch("loop_symphony.tools.claude.AsyncAnthropic"):
        yield ClaudeClient()


@pytest.fixture
def tavily_client(mock_tavily_settings):
    """Create a TavilyClient with mocked settings."""
    yield TavilyClient()


# ---------------------------------------------------------------------------
# TestProtocolConformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    """Verify both clients satisfy the Tool protocol at runtime."""

    def test_claude_is_tool(self, claude_client):
        """ClaudeClient is recognized as a Tool via isinstance."""
        assert isinstance(claude_client, Tool)

    def test_tavily_is_tool(self, tavily_client):
        """TavilyClient is recognized as a Tool via isinstance."""
        assert isinstance(tavily_client, Tool)

    def test_claude_has_name_and_capabilities(self, claude_client):
        """ClaudeClient exposes name and capabilities attributes."""
        assert hasattr(claude_client, "name")
        assert hasattr(claude_client, "capabilities")
        assert isinstance(claude_client.name, str)
        assert isinstance(claude_client.capabilities, frozenset)

    def test_tavily_has_name_and_capabilities(self, tavily_client):
        """TavilyClient exposes name and capabilities attributes."""
        assert hasattr(tavily_client, "name")
        assert hasattr(tavily_client, "capabilities")
        assert isinstance(tavily_client.name, str)
        assert isinstance(tavily_client.capabilities, frozenset)


# ---------------------------------------------------------------------------
# TestManifest
# ---------------------------------------------------------------------------

class TestManifest:
    """Verify manifest() returns correct, immutable ToolManifest instances."""

    def test_claude_returns_manifest(self, claude_client):
        """ClaudeClient.manifest() returns a ToolManifest."""
        m = claude_client.manifest()
        assert isinstance(m, ToolManifest)

    def test_tavily_returns_manifest(self, tavily_client):
        """TavilyClient.manifest() returns a ToolManifest."""
        m = tavily_client.manifest()
        assert isinstance(m, ToolManifest)

    def test_claude_manifest_fields(self, claude_client):
        """Claude manifest has correct name, capabilities, and config_keys."""
        m = claude_client.manifest()
        assert m.name == "claude"
        assert "reasoning" in m.capabilities
        assert "synthesis" in m.capabilities
        assert "analysis" in m.capabilities
        assert "ANTHROPIC_API_KEY" in m.config_keys

    def test_tavily_manifest_fields(self, tavily_client):
        """Tavily manifest has correct name, capabilities, and config_keys."""
        m = tavily_client.manifest()
        assert m.name == "tavily"
        assert "web_search" in m.capabilities
        assert "TAVILY_API_KEY" in m.config_keys

    def test_manifest_capabilities_match_class(self, claude_client, tavily_client):
        """Manifest capabilities equal the class-level capabilities attribute."""
        assert claude_client.manifest().capabilities == claude_client.capabilities
        assert tavily_client.manifest().capabilities == tavily_client.capabilities

    def test_manifest_is_frozen(self, claude_client):
        """ToolManifest is immutable (frozen dataclass)."""
        m = claude_client.manifest()
        with pytest.raises(dataclasses.FrozenInstanceError):
            m.name = "something_else"

    def test_tool_names_are_unique(self, claude_client, tavily_client):
        """Each tool has a distinct name."""
        assert claude_client.manifest().name != tavily_client.manifest().name


# ---------------------------------------------------------------------------
# TestCapabilities
# ---------------------------------------------------------------------------

class TestCapabilities:
    """Verify capability declarations align with actual methods."""

    def test_claude_reasoning_has_complete(self, claude_client):
        """Claude declares 'reasoning' and has complete()."""
        assert "reasoning" in claude_client.capabilities
        assert callable(getattr(claude_client, "complete", None))

    def test_claude_synthesis_has_synthesize(self, claude_client):
        """Claude declares 'synthesis' and has synthesize()."""
        assert "synthesis" in claude_client.capabilities
        assert callable(getattr(claude_client, "synthesize", None))

    def test_claude_analysis_has_analyze(self, claude_client):
        """Claude declares 'analysis' and has analyze()."""
        assert "analysis" in claude_client.capabilities
        assert callable(getattr(claude_client, "analyze", None))

    def test_tavily_web_search_has_search(self, tavily_client):
        """Tavily declares 'web_search' and has search()."""
        assert "web_search" in tavily_client.capabilities
        assert callable(getattr(tavily_client, "search", None))

    def test_claude_does_not_claim_web_search(self, claude_client):
        """Claude should not declare 'web_search'."""
        assert "web_search" not in claude_client.capabilities

    def test_tavily_does_not_claim_reasoning(self, tavily_client):
        """Tavily should not declare 'reasoning'."""
        assert "reasoning" not in tavily_client.capabilities


# ---------------------------------------------------------------------------
# TestHealthCheck
# ---------------------------------------------------------------------------

class TestHealthCheck:
    """Verify health_check() returns bool under success and failure."""

    @pytest.mark.asyncio
    async def test_claude_health_check_success(self, claude_client):
        """Claude health_check returns True when API responds."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="pong")]
        claude_client.client.messages.create = AsyncMock(return_value=mock_response)

        result = await claude_client.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_claude_health_check_failure(self, claude_client):
        """Claude health_check returns False when API raises."""
        claude_client.client.messages.create = AsyncMock(
            side_effect=Exception("Connection error")
        )

        result = await claude_client.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_tavily_health_check_success(self, tavily_client):
        """Tavily health_check returns True when API responds."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        with patch("loop_symphony.tools.tavily.httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tavily_client.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_tavily_health_check_failure(self, tavily_client):
        """Tavily health_check returns False when API raises."""
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(side_effect=Exception("Timeout"))

        with patch("loop_symphony.tools.tavily.httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tavily_client.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_never_raises(self, claude_client, tavily_client):
        """Health checks always return a bool, never raise exceptions."""
        claude_client.client.messages.create = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )

        claude_result = await claude_client.health_check()
        assert isinstance(claude_result, bool)

        with patch("loop_symphony.tools.tavily.httpx.AsyncClient") as mock_async_client:
            mock_async_client.side_effect = RuntimeError("Unexpected")

            tavily_result = await tavily_client.health_check()
            assert isinstance(tavily_result, bool)


# ---------------------------------------------------------------------------
# TestBackwardCompatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Ensure existing methods and constructors remain intact."""

    def test_claude_has_complete(self, claude_client):
        """ClaudeClient still has complete()."""
        assert callable(getattr(claude_client, "complete", None))

    def test_claude_has_analyze(self, claude_client):
        """ClaudeClient still has analyze()."""
        assert callable(getattr(claude_client, "analyze", None))

    def test_claude_has_synthesize(self, claude_client):
        """ClaudeClient still has synthesize()."""
        assert callable(getattr(claude_client, "synthesize", None))

    def test_claude_has_synthesize_with_analysis(self, claude_client):
        """ClaudeClient still has synthesize_with_analysis()."""
        assert callable(getattr(claude_client, "synthesize_with_analysis", None))

    def test_claude_has_analyze_discrepancy(self, claude_client):
        """ClaudeClient still has analyze_discrepancy()."""
        assert callable(getattr(claude_client, "analyze_discrepancy", None))

    def test_tavily_has_search(self, tavily_client):
        """TavilyClient still has search()."""
        assert callable(getattr(tavily_client, "search", None))

    def test_tavily_has_search_multiple(self, tavily_client):
        """TavilyClient still has search_multiple()."""
        assert callable(getattr(tavily_client, "search_multiple", None))

    def test_claude_zero_arg_constructor(self, mock_claude_settings):
        """ClaudeClient() still works with zero args."""
        with patch("loop_symphony.tools.claude.AsyncAnthropic"):
            client = ClaudeClient()
            assert client is not None

    def test_tavily_zero_arg_constructor(self, mock_tavily_settings):
        """TavilyClient() still works with zero args."""
        client = TavilyClient()
        assert client is not None
