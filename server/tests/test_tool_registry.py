"""Tests for ToolRegistry: registration, capability lookup, and resolution."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.tools.base import Tool, ToolManifest
from loop_symphony.tools.registry import CapabilityError, ToolRegistry
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.tools.tavily import TavilyClient
from loop_symphony.instruments.note import NoteInstrument
from loop_symphony.instruments.research import ResearchInstrument


# ---------------------------------------------------------------------------
# Helpers — lightweight mock tools
# ---------------------------------------------------------------------------

def _make_tool(
    name: str,
    capabilities: frozenset[str],
    healthy: bool = True,
) -> Tool:
    """Create a lightweight mock that satisfies the Tool protocol."""
    tool = MagicMock(spec=Tool)
    tool.name = name
    tool.capabilities = capabilities
    tool.manifest.return_value = ToolManifest(
        name=name,
        version="0.1.0",
        description=f"Mock {name}",
        capabilities=capabilities,
        config_keys=frozenset(),
    )
    tool.health_check = AsyncMock(return_value=healthy)
    return tool


@pytest.fixture
def registry():
    """Empty registry."""
    return ToolRegistry()


@pytest.fixture
def reasoning_tool():
    return _make_tool("reasoning_llm", frozenset({"reasoning", "synthesis", "analysis"}))


@pytest.fixture
def search_tool():
    return _make_tool("web_search_api", frozenset({"web_search"}))


# ---------------------------------------------------------------------------
# TestRegistration
# ---------------------------------------------------------------------------

class TestRegistration:
    """Verify tool registration and name-based lookup."""

    def test_register_tool(self, registry, reasoning_tool):
        """A tool can be registered successfully."""
        registry.register(reasoning_tool)
        assert len(registry) == 1

    def test_duplicate_name_raises(self, registry, reasoning_tool):
        """Registering a tool with the same name raises ValueError."""
        registry.register(reasoning_tool)
        duplicate = _make_tool(reasoning_tool.name, frozenset({"other"}))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(duplicate)

    def test_get_by_name_returns_tool(self, registry, reasoning_tool):
        """get_by_name returns the registered tool."""
        registry.register(reasoning_tool)
        assert registry.get_by_name("reasoning_llm") is reasoning_tool

    def test_get_by_name_returns_none_for_unknown(self, registry):
        """get_by_name returns None when name is not registered."""
        assert registry.get_by_name("nonexistent") is None

    def test_get_all_returns_all_tools(self, registry, reasoning_tool, search_tool):
        """get_all returns all registered tools."""
        registry.register(reasoning_tool)
        registry.register(search_tool)
        all_tools = registry.get_all()
        assert len(all_tools) == 2
        assert reasoning_tool in all_tools
        assert search_tool in all_tools


# ---------------------------------------------------------------------------
# TestCapabilityLookup
# ---------------------------------------------------------------------------

class TestCapabilityLookup:
    """Verify capability-based tool lookup."""

    def test_get_by_capability_returns_tool(self, registry, reasoning_tool):
        """get_by_capability returns a tool that has the capability."""
        registry.register(reasoning_tool)
        assert registry.get_by_capability("reasoning") is reasoning_tool

    def test_get_by_capability_returns_none_for_unknown(self, registry):
        """get_by_capability returns None for unregistered capability."""
        assert registry.get_by_capability("teleportation") is None

    def test_multiple_tools_same_capability_returns_first(self, registry):
        """When multiple tools share a capability, first registered wins."""
        tool_a = _make_tool("tool_a", frozenset({"reasoning"}))
        tool_b = _make_tool("tool_b", frozenset({"reasoning"}))
        registry.register(tool_a)
        registry.register(tool_b)
        assert registry.get_by_capability("reasoning") is tool_a

    def test_tool_found_via_any_capability(self, registry, reasoning_tool):
        """A tool with multiple capabilities is found via any of them."""
        registry.register(reasoning_tool)
        assert registry.get_by_capability("reasoning") is reasoning_tool
        assert registry.get_by_capability("synthesis") is reasoning_tool
        assert registry.get_by_capability("analysis") is reasoning_tool


# ---------------------------------------------------------------------------
# TestResolve
# ---------------------------------------------------------------------------

class TestResolve:
    """Verify capability resolution for instruments."""

    def test_resolve_required_capabilities(self, registry, reasoning_tool):
        """Resolves all required capabilities successfully."""
        registry.register(reasoning_tool)
        result = registry.resolve(frozenset({"reasoning"}))
        assert "reasoning" in result
        assert result["reasoning"] is reasoning_tool

    def test_missing_required_raises_capability_error(self, registry):
        """Missing required capability raises CapabilityError."""
        with pytest.raises(CapabilityError, match="web_search"):
            registry.resolve(frozenset({"web_search"}))

    def test_optional_included_when_available(
        self, registry, reasoning_tool, search_tool
    ):
        """Optional capabilities are included when a tool provides them."""
        registry.register(reasoning_tool)
        registry.register(search_tool)
        result = registry.resolve(
            required=frozenset({"reasoning"}),
            optional=frozenset({"web_search"}),
        )
        assert "reasoning" in result
        assert "web_search" in result

    def test_missing_optional_does_not_raise(self, registry, reasoning_tool):
        """Missing optional capabilities do not raise, just omitted."""
        registry.register(reasoning_tool)
        result = registry.resolve(
            required=frozenset({"reasoning"}),
            optional=frozenset({"web_search"}),
        )
        assert "reasoning" in result
        assert "web_search" not in result

    def test_mixed_required_and_optional(
        self, registry, reasoning_tool, search_tool
    ):
        """Mixed required + optional resolution works correctly."""
        registry.register(reasoning_tool)
        registry.register(search_tool)
        result = registry.resolve(
            required=frozenset({"reasoning", "web_search"}),
            optional=frozenset({"synthesis", "analysis"}),
        )
        assert result["reasoning"] is reasoning_tool
        assert result["web_search"] is search_tool
        assert result["synthesis"] is reasoning_tool
        assert result["analysis"] is reasoning_tool

    def test_empty_required_and_optional(self, registry):
        """Empty required + empty optional returns empty dict."""
        result = registry.resolve(frozenset(), frozenset())
        assert result == {}


# ---------------------------------------------------------------------------
# TestConvenience
# ---------------------------------------------------------------------------

class TestConvenience:
    """Verify __len__ and __contains__ convenience methods."""

    def test_len_returns_tool_count(self, registry, reasoning_tool, search_tool):
        """len(registry) returns number of registered tools."""
        assert len(registry) == 0
        registry.register(reasoning_tool)
        assert len(registry) == 1
        registry.register(search_tool)
        assert len(registry) == 2

    def test_contains_checks_name(self, registry, reasoning_tool):
        """'name' in registry checks tool name presence."""
        registry.register(reasoning_tool)
        assert "reasoning_llm" in registry
        assert "nonexistent" not in registry


# ---------------------------------------------------------------------------
# TestHealthCheck
# ---------------------------------------------------------------------------

class TestHealthCheck:
    """Verify health_check_all aggregation."""

    @pytest.mark.asyncio
    async def test_health_check_all_returns_status(self, registry):
        """health_check_all returns dict of name -> bool."""
        healthy = _make_tool("healthy_tool", frozenset({"a"}), healthy=True)
        unhealthy = _make_tool("sick_tool", frozenset({"b"}), healthy=False)
        registry.register(healthy)
        registry.register(unhealthy)

        results = await registry.health_check_all()

        assert results == {"healthy_tool": True, "sick_tool": False}

    @pytest.mark.asyncio
    async def test_health_check_empty_registry(self, registry):
        """health_check_all on empty registry returns empty dict."""
        results = await registry.health_check_all()
        assert results == {}


# ---------------------------------------------------------------------------
# TestIntegrationWithRealTools
# ---------------------------------------------------------------------------

class TestIntegrationWithRealTools:
    """Verify registry works with real ClaudeClient and TavilyClient."""

    @pytest.fixture
    def claude_client(self):
        with patch("loop_symphony.tools.claude.get_settings") as mock:
            settings = MagicMock()
            settings.anthropic_api_key = "test-key"
            settings.claude_model = "test-model"
            settings.claude_max_tokens = 1024
            mock.return_value = settings
            with patch("loop_symphony.tools.claude.AsyncAnthropic"):
                yield ClaudeClient()

    @pytest.fixture
    def tavily_client(self):
        with patch("loop_symphony.tools.tavily.get_settings") as mock:
            settings = MagicMock()
            settings.tavily_api_key = "test-key"
            mock.return_value = settings
            yield TavilyClient()

    def test_register_real_tools(self, registry, claude_client, tavily_client):
        """Real ClaudeClient and TavilyClient register successfully."""
        registry.register(claude_client)
        registry.register(tavily_client)
        assert len(registry) == 2
        assert "claude" in registry
        assert "tavily" in registry

    def test_resolve_note_capabilities(self, registry, claude_client, tavily_client):
        """Registry resolves NoteInstrument's required capabilities."""
        registry.register(claude_client)
        registry.register(tavily_client)
        result = registry.resolve(NoteInstrument.required_capabilities)
        assert "reasoning" in result
        assert result["reasoning"] is claude_client

    def test_resolve_research_capabilities(
        self, registry, claude_client, tavily_client
    ):
        """Registry resolves ResearchInstrument's required + optional capabilities."""
        registry.register(claude_client)
        registry.register(tavily_client)
        result = registry.resolve(
            ResearchInstrument.required_capabilities,
            ResearchInstrument.optional_capabilities,
        )
        assert result["reasoning"] is claude_client
        assert result["web_search"] is tavily_client
        assert result["synthesis"] is claude_client
        assert result["analysis"] is claude_client
