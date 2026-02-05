"""Tests for registry wiring in production routes."""

import pytest
from unittest.mock import MagicMock, patch

from loop_symphony.api import routes
from loop_symphony.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons between tests."""
    routes._conductor = None
    routes._registry = None
    routes._db_client = None
    yield
    routes._conductor = None
    routes._registry = None
    routes._db_client = None


class _MockContext:
    """Holds all mocks so tests can assert on instrument construction."""

    def __init__(self):
        self._claude_patch = patch("loop_symphony.api.routes.ClaudeClient")
        self._tavily_patch = patch("loop_symphony.api.routes.TavilyClient")
        self._note_patch = patch("loop_symphony.manager.conductor.NoteInstrument")
        self._research_patch = patch("loop_symphony.manager.conductor.ResearchInstrument")
        self._synthesis_patch = patch("loop_symphony.manager.conductor.SynthesisInstrument")
        self._vision_patch = patch("loop_symphony.manager.conductor.VisionInstrument")

    def __enter__(self):
        self.claude_cls = self._claude_patch.start()
        self.tavily_cls = self._tavily_patch.start()
        self.note_cls = self._note_patch.start()
        self.research_cls = self._research_patch.start()
        self.synthesis_cls = self._synthesis_patch.start()
        self.vision_cls = self._vision_patch.start()

        # Mock tool instances with correct protocol attributes
        self.claude = MagicMock()
        self.claude.name = "claude"
        self.claude.capabilities = frozenset({"reasoning", "synthesis", "analysis", "vision"})
        self.claude_cls.return_value = self.claude

        self.tavily = MagicMock()
        self.tavily.name = "tavily"
        self.tavily.capabilities = frozenset({"web_search"})
        self.tavily_cls.return_value = self.tavily

        # Restore real capability attributes on instrument class mocks
        self.note_cls.required_capabilities = frozenset({"reasoning"})
        self.note_cls.optional_capabilities = frozenset()
        self.research_cls.required_capabilities = frozenset({"reasoning", "web_search"})
        self.research_cls.optional_capabilities = frozenset({"synthesis", "analysis"})
        self.synthesis_cls.required_capabilities = frozenset({"reasoning", "synthesis"})
        self.synthesis_cls.optional_capabilities = frozenset()
        self.vision_cls.required_capabilities = frozenset({"reasoning", "vision"})
        self.vision_cls.optional_capabilities = frozenset()

        return self

    def __exit__(self, *args):
        self._claude_patch.stop()
        self._tavily_patch.stop()
        self._note_patch.stop()
        self._research_patch.stop()
        self._synthesis_patch.stop()
        self._vision_patch.stop()


# ---------------------------------------------------------------------------
# TestBuildRegistry
# ---------------------------------------------------------------------------

class TestBuildRegistry:
    """Verify _build_registry() creates a properly populated registry."""

    def test_registry_has_both_tools(self):
        """_build_registry registers ClaudeClient and TavilyClient."""
        with _MockContext():
            registry = routes._build_registry()

        assert isinstance(registry, ToolRegistry)
        assert len(registry) == 2
        assert "claude" in registry
        assert "tavily" in registry

    def test_registry_resolves_reasoning(self):
        """Registry can resolve the 'reasoning' capability."""
        with _MockContext() as ctx:
            registry = routes._build_registry()

        assert registry.get_by_capability("reasoning") is ctx.claude

    def test_registry_resolves_web_search(self):
        """Registry can resolve the 'web_search' capability."""
        with _MockContext() as ctx:
            registry = routes._build_registry()

        assert registry.get_by_capability("web_search") is ctx.tavily


# ---------------------------------------------------------------------------
# TestGetConductorWithRegistry
# ---------------------------------------------------------------------------

class TestGetConductorWithRegistry:
    """Verify get_conductor() creates a registry-backed conductor."""

    def test_conductor_has_registry(self):
        """Production conductor has a ToolRegistry."""
        with _MockContext():
            conductor = routes.get_conductor()

        assert conductor.registry is not None
        assert isinstance(conductor.registry, ToolRegistry)

    def test_registry_contains_both_tools(self):
        """Production conductor's registry has claude and tavily."""
        with _MockContext():
            conductor = routes.get_conductor()

        assert "claude" in conductor.registry
        assert "tavily" in conductor.registry

    def test_conductor_has_all_instruments(self):
        """Production conductor has note, research, synthesis, and vision instruments."""
        with _MockContext():
            conductor = routes.get_conductor()

        assert "note" in conductor.instruments
        assert "research" in conductor.instruments
        assert "synthesis" in conductor.instruments
        assert "vision" in conductor.instruments

    def test_note_built_with_claude_from_registry(self):
        """NoteInstrument is constructed with the claude tool from registry."""
        with _MockContext() as ctx:
            routes.get_conductor()
            ctx.note_cls.assert_called_once_with(claude=ctx.claude)

    def test_research_built_with_tools_from_registry(self):
        """ResearchInstrument is constructed with claude and tavily from registry."""
        with _MockContext() as ctx:
            routes.get_conductor()
            ctx.research_cls.assert_called_once_with(
                claude=ctx.claude, tavily=ctx.tavily,
            )

    def test_singleton_behavior(self):
        """get_conductor() returns the same instance on subsequent calls."""
        with _MockContext():
            first = routes.get_conductor()
            second = routes.get_conductor()

        assert first is second

    def test_module_registry_set(self):
        """get_conductor() sets the module-level _registry."""
        assert routes._registry is None

        with _MockContext():
            routes.get_conductor()

        assert routes._registry is not None
        assert isinstance(routes._registry, ToolRegistry)


# ---------------------------------------------------------------------------
# TestHealthEndpointWithTools
# ---------------------------------------------------------------------------

class TestHealthEndpointWithTools:
    """Verify health endpoint includes tool info when registry is initialized."""

    @pytest.mark.asyncio
    async def test_health_without_registry(self):
        """Health endpoint works when registry not yet initialized."""
        response = await routes.health()

        assert response["status"] == "ok"
        assert "tools" not in response

    @pytest.mark.asyncio
    async def test_health_with_registry(self):
        """Health endpoint includes tool names after registry initialization."""
        with _MockContext():
            routes.get_conductor()

        response = await routes.health()

        assert response["status"] == "ok"
        assert "tools" in response
        assert response["tools"] == ["claude", "tavily"]

    @pytest.mark.asyncio
    async def test_health_tools_sorted(self):
        """Tool names in health response are sorted alphabetically."""
        with _MockContext():
            routes.get_conductor()

        response = await routes.health()

        assert response["tools"] == sorted(response["tools"])
