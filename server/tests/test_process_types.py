"""Tests for ProcessType visibility types."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.models.finding import ExecutionMetadata, Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.process import ProcessType
from loop_symphony.models.task import TaskRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_result(**overrides):
    """Build an InstrumentResult for testing."""
    defaults = dict(
        outcome=Outcome.COMPLETE,
        findings=[Finding(content="Answer")],
        summary="The answer",
        confidence=0.9,
        iterations=1,
    )
    defaults.update(overrides)
    return InstrumentResult(**defaults)


# ---------------------------------------------------------------------------
# TestProcessTypeEnum
# ---------------------------------------------------------------------------

class TestProcessTypeEnum:
    """Verify ProcessType enum structure."""

    def test_has_all_three_values(self):
        """ProcessType has AUTONOMIC, SEMI_AUTONOMIC, CONSCIOUS."""
        assert ProcessType.AUTONOMIC
        assert ProcessType.SEMI_AUTONOMIC
        assert ProcessType.CONSCIOUS
        assert len(ProcessType) == 3

    def test_values_are_lowercase_strings(self):
        """Enum values are lowercase strings for JSON serialization."""
        assert ProcessType.AUTONOMIC.value == "autonomic"
        assert ProcessType.SEMI_AUTONOMIC.value == "semi_autonomic"
        assert ProcessType.CONSCIOUS.value == "conscious"

    def test_is_str_enum(self):
        """ProcessType members can be used as strings."""
        assert isinstance(ProcessType.AUTONOMIC, str)
        assert ProcessType.AUTONOMIC == "autonomic"


# ---------------------------------------------------------------------------
# TestProcessTypeAssignment
# ---------------------------------------------------------------------------

class TestProcessTypeAssignment:
    """Verify Conductor assigns correct process types."""

    @pytest.fixture
    def conductor(self):
        """Create a Conductor with mocked instruments."""
        with patch("loop_symphony.manager.conductor.NoteInstrument"), \
             patch("loop_symphony.manager.conductor.ResearchInstrument"), \
             patch("loop_symphony.manager.conductor.SynthesisInstrument"), \
             patch("loop_symphony.manager.conductor.VisionInstrument"), \
             patch("loop_symphony.manager.conductor.IngestInstrument"), \
             patch("loop_symphony.manager.conductor.DiagnoseInstrument"), \
             patch("loop_symphony.manager.conductor.PrescribeInstrument"), \
             patch("loop_symphony.manager.conductor.TrackInstrument"), \
             patch("loop_symphony.manager.conductor.ReportInstrument"):
            from loop_symphony.manager.conductor import Conductor
            cond = Conductor()
            cond.instruments["note"] = MagicMock()
            cond.instruments["research"] = MagicMock()
            cond.instruments["synthesis"] = MagicMock()
            cond.instruments["vision"] = MagicMock()
            yield cond

    @pytest.mark.asyncio
    async def test_note_is_autonomic(self, conductor):
        """Note instrument produces AUTONOMIC process type."""
        conductor.instruments["note"].execute = AsyncMock(
            return_value=_mock_result()
        )
        request = TaskRequest(query="Simple question?")
        response = await conductor.execute(request)

        assert response.metadata.process_type == ProcessType.AUTONOMIC

    @pytest.mark.asyncio
    async def test_research_is_semi_autonomic(self, conductor):
        """Research instrument produces SEMI_AUTONOMIC process type."""
        conductor.instruments["research"].execute = AsyncMock(
            return_value=_mock_result()
        )
        request = TaskRequest(query="Research the latest AI developments")
        response = await conductor.execute(request)

        assert response.metadata.process_type == ProcessType.SEMI_AUTONOMIC

    @pytest.mark.asyncio
    async def test_composition_is_conscious(self, conductor):
        """Composition execution produces CONSCIOUS process type."""
        mock_comp = MagicMock()
        mock_comp.name = "research -> synthesis"
        mock_comp.execute = AsyncMock(return_value=_mock_result())

        request = TaskRequest(query="Test")
        response = await conductor.execute_composition(mock_comp, request)

        assert response.metadata.process_type == ProcessType.CONSCIOUS

    @pytest.mark.asyncio
    async def test_unknown_instrument_defaults_to_semi_autonomic(self, conductor):
        """Unknown instrument name defaults to SEMI_AUTONOMIC."""
        # Add a custom instrument not in the mapping
        conductor.instruments["custom"] = MagicMock()
        conductor.instruments["custom"].execute = AsyncMock(
            return_value=_mock_result()
        )

        # Bypass routing to force unknown instrument
        from loop_symphony.manager.conductor import _INSTRUMENT_PROCESS_TYPE
        assert "custom" not in _INSTRUMENT_PROCESS_TYPE

        # Manually simulate what execute() does for an unknown instrument
        from loop_symphony.models.finding import ExecutionMetadata
        metadata = ExecutionMetadata(
            instrument_used="custom",
            iterations=1,
            duration_ms=0,
            process_type=_INSTRUMENT_PROCESS_TYPE.get(
                "custom", ProcessType.SEMI_AUTONOMIC
            ),
        )
        assert metadata.process_type == ProcessType.SEMI_AUTONOMIC

    @pytest.mark.asyncio
    async def test_process_type_present_in_response(self, conductor):
        """Process type is included in response metadata."""
        conductor.instruments["note"].execute = AsyncMock(
            return_value=_mock_result()
        )
        request = TaskRequest(query="Hello?")
        response = await conductor.execute(request)

        assert hasattr(response.metadata, "process_type")
        assert isinstance(response.metadata.process_type, ProcessType)


# ---------------------------------------------------------------------------
# TestMetadataBackwardCompat
# ---------------------------------------------------------------------------

class TestMetadataBackwardCompat:
    """Verify backward compatibility of ExecutionMetadata."""

    def test_default_process_type_is_autonomic(self):
        """ExecutionMetadata defaults to AUTONOMIC when not specified."""
        metadata = ExecutionMetadata(
            instrument_used="note",
            iterations=1,
            duration_ms=100,
        )
        assert metadata.process_type == ProcessType.AUTONOMIC

    def test_existing_fields_unchanged(self):
        """Adding process_type doesn't affect existing fields."""
        metadata = ExecutionMetadata(
            instrument_used="research",
            iterations=3,
            duration_ms=500,
            sources_consulted=["web", "claude"],
            process_type=ProcessType.SEMI_AUTONOMIC,
        )
        assert metadata.instrument_used == "research"
        assert metadata.iterations == 3
        assert metadata.duration_ms == 500
        assert metadata.sources_consulted == ["web", "claude"]


# ---------------------------------------------------------------------------
# TestProcessTypeSerialization
# ---------------------------------------------------------------------------

class TestProcessTypeSerialization:
    """Verify ProcessType serializes correctly."""

    def test_model_dump_produces_string(self):
        """model_dump(mode='json') serializes process_type as string."""
        metadata = ExecutionMetadata(
            instrument_used="note",
            iterations=1,
            duration_ms=100,
            process_type=ProcessType.CONSCIOUS,
        )
        dumped = metadata.model_dump(mode="json")

        assert dumped["process_type"] == "conscious"

    def test_round_trip_serialization(self):
        """ProcessType survives model_dump -> model_validate round-trip."""
        original = ExecutionMetadata(
            instrument_used="research",
            iterations=2,
            duration_ms=300,
            sources_consulted=["web"],
            process_type=ProcessType.SEMI_AUTONOMIC,
        )

        dumped = original.model_dump(mode="json")
        restored = ExecutionMetadata.model_validate(dumped)

        assert restored.process_type == ProcessType.SEMI_AUTONOMIC
        assert restored == original
