"""Tests for Conductor with ToolRegistry integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.manager.conductor import Conductor
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskRequest
from loop_symphony.tools.base import Tool, ToolManifest
from loop_symphony.tools.registry import CapabilityError, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_tool(name: str, capabilities: frozenset[str]) -> Tool:
    """Create a lightweight mock satisfying the Tool protocol."""
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
    tool.health_check = AsyncMock(return_value=True)
    return tool


def _build_registry() -> tuple[ToolRegistry, Tool, Tool]:
    """Build a registry with mock claude and tavily tools."""
    claude = _make_mock_tool(
        "claude", frozenset({"reasoning", "synthesis", "analysis", "vision"})
    )
    tavily = _make_mock_tool("tavily", frozenset({"web_search"}))
    registry = ToolRegistry()
    registry.register(claude)
    registry.register(tavily)
    return registry, claude, tavily


def _patch_instrument_classes():
    """Patch all instrument classes with their real capability attributes.

    When instrument classes are patched at the conductor module level, the mocks
    lose their class attributes. _build_instrument reads
    required_capabilities/optional_capabilities from these names, so we must
    restore them on the mocks.
    """
    note_patch = patch("loop_symphony.manager.conductor.NoteInstrument")
    research_patch = patch("loop_symphony.manager.conductor.ResearchInstrument")
    synthesis_patch = patch("loop_symphony.manager.conductor.SynthesisInstrument")
    vision_patch = patch("loop_symphony.manager.conductor.VisionInstrument")

    class _Ctx:
        """Context manager that yields (mock_note_cls, mock_research_cls)."""

        def __enter__(self):
            self.mock_note = note_patch.start()
            self.mock_research = research_patch.start()
            self.mock_synthesis = synthesis_patch.start()
            self.mock_vision = vision_patch.start()
            # Restore real capability class attributes on the mocks
            self.mock_note.required_capabilities = frozenset({"reasoning"})
            self.mock_note.optional_capabilities = frozenset()
            self.mock_research.required_capabilities = frozenset({"reasoning", "web_search"})
            self.mock_research.optional_capabilities = frozenset({"synthesis", "analysis"})
            self.mock_synthesis.required_capabilities = frozenset({"reasoning", "synthesis"})
            self.mock_synthesis.optional_capabilities = frozenset()
            self.mock_vision.required_capabilities = frozenset({"reasoning", "vision"})
            self.mock_vision.optional_capabilities = frozenset()
            return self.mock_note, self.mock_research

        def __exit__(self, *args):
            note_patch.stop()
            research_patch.stop()
            synthesis_patch.stop()
            vision_patch.stop()

    return _Ctx()


# ---------------------------------------------------------------------------
# TestConductorWithRegistry
# ---------------------------------------------------------------------------

class TestConductorWithRegistry:
    """Verify Conductor builds instruments via registry."""

    def test_note_instrument_gets_claude_from_registry(self):
        """NoteInstrument receives the claude tool from the registry."""
        registry, claude, _ = _build_registry()

        with _patch_instrument_classes() as (mock_note_cls, mock_res_cls):
            conductor = Conductor(registry=registry)

        mock_note_cls.assert_called_once_with(claude=claude)

    def test_research_instrument_gets_tools_from_registry(self):
        """ResearchInstrument receives claude and tavily from the registry."""
        registry, claude, tavily = _build_registry()

        with _patch_instrument_classes() as (mock_note_cls, mock_res_cls):
            conductor = Conductor(registry=registry)

        mock_res_cls.assert_called_once_with(claude=claude, tavily=tavily)

    @pytest.mark.asyncio
    async def test_execution_through_registry_conductor(self):
        """End-to-end execution works with registry-backed conductor."""
        registry, claude, tavily = _build_registry()

        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[Finding(content="Registry answer")],
            summary="Registry answer",
            confidence=0.9,
            iterations=1,
        )

        with _patch_instrument_classes() as (mock_note_cls, mock_res_cls):
            mock_note_cls.return_value.execute = AsyncMock(return_value=mock_result)
            conductor = Conductor(registry=registry)

            request = TaskRequest(query="Simple question?")
            response = await conductor.execute(request)

        assert response.outcome == Outcome.COMPLETE
        assert response.summary == "Registry answer"
        assert response.metadata.instrument_used == "note"

    @pytest.mark.asyncio
    async def test_routing_unchanged_with_registry(self):
        """Routing logic is the same regardless of registry presence."""
        registry, _, _ = _build_registry()

        with _patch_instrument_classes():
            conductor = Conductor(registry=registry)

            simple = TaskRequest(query="What is 2+2?")
            assert await conductor.analyze_and_route(simple) == "note"

            research = TaskRequest(query="Research the latest AI developments")
            assert await conductor.analyze_and_route(research) == "research"

    def test_missing_capability_raises_at_construction(self):
        """Missing required capability raises CapabilityError during init."""
        registry = ToolRegistry()
        # Only register a tool with "web_search", missing "reasoning"
        tavily = _make_mock_tool("tavily", frozenset({"web_search"}))
        registry.register(tavily)

        with pytest.raises(CapabilityError, match="reasoning"):
            Conductor(registry=registry)


# ---------------------------------------------------------------------------
# TestConductorBackwardCompat
# ---------------------------------------------------------------------------

class TestConductorBackwardCompat:
    """Verify zero-arg Conductor still works."""

    def test_zero_arg_constructor_works(self):
        """Conductor() without registry still works."""
        with patch("loop_symphony.manager.conductor.NoteInstrument"), \
             patch("loop_symphony.manager.conductor.ResearchInstrument"), \
             patch("loop_symphony.manager.conductor.SynthesisInstrument"), \
             patch("loop_symphony.manager.conductor.VisionInstrument"):
            conductor = Conductor()
            assert conductor.registry is None

    def test_zero_arg_has_all_instruments(self):
        """Zero-arg conductor creates all instruments."""
        with patch("loop_symphony.manager.conductor.NoteInstrument"), \
             patch("loop_symphony.manager.conductor.ResearchInstrument"), \
             patch("loop_symphony.manager.conductor.SynthesisInstrument"), \
             patch("loop_symphony.manager.conductor.VisionInstrument"):
            conductor = Conductor()
            assert "note" in conductor.instruments
            assert "research" in conductor.instruments
            assert "synthesis" in conductor.instruments
            assert "vision" in conductor.instruments

    @pytest.mark.asyncio
    async def test_zero_arg_executes_correctly(self):
        """Zero-arg conductor executes tasks correctly."""
        mock_result = InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[Finding(content="Answer")],
            summary="The answer",
            confidence=0.9,
            iterations=1,
        )

        with patch("loop_symphony.manager.conductor.NoteInstrument") as mock_note, \
             patch("loop_symphony.manager.conductor.ResearchInstrument"), \
             patch("loop_symphony.manager.conductor.SynthesisInstrument"), \
             patch("loop_symphony.manager.conductor.VisionInstrument"):
            mock_note.return_value.execute = AsyncMock(return_value=mock_result)
            conductor = Conductor()

            request = TaskRequest(query="Simple question?")
            response = await conductor.execute(request)

        assert response.outcome == Outcome.COMPLETE
        assert response.metadata.instrument_used == "note"
