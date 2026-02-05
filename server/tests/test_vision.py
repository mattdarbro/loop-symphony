"""Tests for Vision instrument."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loop_symphony.instruments.base import InstrumentResult
from loop_symphony.instruments.vision import VisionInstrument
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext, TaskRequest
from loop_symphony.tools.claude import ClaudeClient, ImageInput


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_BASE64 = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
SAMPLE_PNG_BASE64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEU=="
SAMPLE_URL_JPG = "https://example.com/photo.jpg"
SAMPLE_URL_PNG = "https://example.com/image.png"
SAMPLE_URL_NO_EXT = "https://storage.example.com/abc123"

SAMPLE_JSON_RESPONSE = json.dumps({
    "observations": ["A cat on a table", "Blue background"],
    "analysis": "The image shows a cat sitting on a wooden table.",
    "confidence": 0.9,
})

SAMPLE_LOW_CONFIDENCE_RESPONSE = json.dumps({
    "observations": ["Something blurry"],
    "analysis": "The image is unclear.",
    "confidence": 0.4,
})


# ---------------------------------------------------------------------------
# TestParseAttachments
# ---------------------------------------------------------------------------

class TestParseAttachments:
    """Tests for attachment parsing logic."""

    def test_parses_base64_jpeg(self):
        """Parses data:image/jpeg;base64,... correctly."""
        result = VisionInstrument.parse_attachments([SAMPLE_BASE64])
        assert len(result) == 1
        assert result[0].source_type == "base64"
        assert result[0].media_type == "image/jpeg"
        assert result[0].data == "/9j/4AAQSkZJRg=="

    def test_parses_base64_png(self):
        """Parses data:image/png;base64,... correctly."""
        result = VisionInstrument.parse_attachments([SAMPLE_PNG_BASE64])
        assert len(result) == 1
        assert result[0].source_type == "base64"
        assert result[0].media_type == "image/png"
        assert result[0].data == "iVBORw0KGgoAAAANSUhEU=="

    def test_parses_url_with_jpg_extension(self):
        """Parses HTTPS URL ending in .jpg."""
        result = VisionInstrument.parse_attachments([SAMPLE_URL_JPG])
        assert len(result) == 1
        assert result[0].source_type == "url"
        assert result[0].media_type == "image/jpeg"
        assert result[0].data == SAMPLE_URL_JPG

    def test_parses_url_with_png_extension(self):
        """Parses HTTPS URL ending in .png."""
        result = VisionInstrument.parse_attachments([SAMPLE_URL_PNG])
        assert len(result) == 1
        assert result[0].source_type == "url"
        assert result[0].media_type == "image/png"

    def test_skips_non_image_attachments(self):
        """Plain text strings are skipped."""
        result = VisionInstrument.parse_attachments([
            "just some text",
            "file:///local/path.txt",
        ])
        assert len(result) == 0

    def test_parses_multiple_images(self):
        """Multiple mixed attachments parsed correctly."""
        result = VisionInstrument.parse_attachments([
            SAMPLE_BASE64,
            SAMPLE_URL_JPG,
        ])
        assert len(result) == 2
        assert result[0].source_type == "base64"
        assert result[1].source_type == "url"

    def test_handles_url_with_query_params(self):
        """URL with query params has extension detected before params."""
        result = VisionInstrument.parse_attachments([
            "https://example.com/photo.png?token=abc&size=large",
        ])
        assert len(result) == 1
        assert result[0].media_type == "image/png"

    def test_empty_attachments_returns_empty(self):
        """Empty list returns empty list."""
        assert VisionInstrument.parse_attachments([]) == []

    def test_url_without_extension_defaults_to_jpeg(self):
        """HTTPS URL without recognized extension defaults to image/jpeg."""
        result = VisionInstrument.parse_attachments([SAMPLE_URL_NO_EXT])
        assert len(result) == 1
        assert result[0].media_type == "image/jpeg"
        assert result[0].source_type == "url"


# ---------------------------------------------------------------------------
# TestVisionCapabilities
# ---------------------------------------------------------------------------

class TestVisionCapabilities:
    """Tests for capability declarations."""

    def test_required_capabilities(self):
        """Vision requires reasoning and vision."""
        assert VisionInstrument.required_capabilities == frozenset(
            {"reasoning", "vision"}
        )

    def test_max_iterations(self):
        """Max iterations is 3."""
        assert VisionInstrument.max_iterations == 3

    def test_name(self):
        """Instrument name is 'vision'."""
        assert VisionInstrument.name == "vision"


# ---------------------------------------------------------------------------
# TestVisionToolInjection
# ---------------------------------------------------------------------------

class TestVisionToolInjection:
    """Tests for tool injection pattern."""

    def test_accepts_injected_claude(self):
        """VisionInstrument accepts injected claude client."""
        mock_claude = MagicMock(spec=ClaudeClient)
        inst = VisionInstrument(claude=mock_claude)
        assert inst.claude is mock_claude

    @patch("loop_symphony.instruments.vision.ClaudeClient")
    @patch("loop_symphony.instruments.vision.TerminationEvaluator")
    def test_zero_arg_construction(self, mock_term, mock_claude):
        """Zero-arg construction creates default ClaudeClient."""
        inst = VisionInstrument()
        mock_claude.assert_called_once()

    def test_injected_claude_is_not_replaced(self):
        """Injected claude is used, not replaced with default."""
        mock_claude = MagicMock(spec=ClaudeClient)
        inst = VisionInstrument(claude=mock_claude)
        assert inst.claude is mock_claude


# ---------------------------------------------------------------------------
# TestVisionExecution
# ---------------------------------------------------------------------------

class TestVisionExecution:
    """Tests for execute() method."""

    def _make_instrument(self):
        """Create a VisionInstrument with mocked dependencies."""
        claude = MagicMock()
        claude.complete_with_images = AsyncMock(return_value=SAMPLE_JSON_RESPONSE)
        claude.complete = AsyncMock(return_value="Final summary of analysis.")
        claude._parse_json_response = ClaudeClient._parse_json_response

        term = MagicMock()
        # Default: terminate after first iteration (high confidence)
        term.calculate_confidence = MagicMock(return_value=0.85)
        from loop_symphony.termination.evaluator import TerminationResult
        term.evaluate = MagicMock(return_value=TerminationResult(
            should_terminate=True,
            outcome=Outcome.COMPLETE,
            reason="Confidence converged",
        ))

        inst = VisionInstrument(claude=claude)
        inst.termination = term
        return inst

    @pytest.mark.asyncio
    async def test_returns_bounded_with_no_images(self):
        """No images returns BOUNDED with helpful suggestion."""
        inst = self._make_instrument()
        ctx = TaskContext()  # no attachments
        result = await inst.execute("Describe this", ctx)

        assert result.outcome == Outcome.BOUNDED
        assert result.confidence == 0.0
        assert len(result.findings) == 0
        assert "No images" in result.summary

    @pytest.mark.asyncio
    async def test_single_iteration_high_confidence(self):
        """High confidence on first iteration terminates early."""
        inst = self._make_instrument()
        ctx = TaskContext(attachments=[SAMPLE_BASE64])
        result = await inst.execute("What is in this image?", ctx)

        assert result.outcome == Outcome.COMPLETE
        assert result.iterations == 1
        assert len(result.findings) >= 1
        inst.claude.complete_with_images.assert_called_once()

    @pytest.mark.asyncio
    async def test_iterates_on_low_confidence(self):
        """Low confidence triggers additional iterations."""
        inst = self._make_instrument()

        # Make termination NOT trigger on first call, trigger on second
        from loop_symphony.termination.evaluator import TerminationResult
        call_count = 0

        def mock_evaluate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                return TerminationResult(
                    should_terminate=True,
                    outcome=Outcome.COMPLETE,
                    reason="Converged",
                )
            return TerminationResult(
                should_terminate=False,
                outcome=None,
                reason="Continue",
            )

        inst.termination.evaluate = mock_evaluate

        ctx = TaskContext(attachments=[SAMPLE_BASE64])
        result = await inst.execute("Describe", ctx)

        assert result.iterations == 2
        assert inst.claude.complete_with_images.call_count == 2

    @pytest.mark.asyncio
    async def test_bounded_on_max_iterations(self):
        """Reaches max iterations returns BOUNDED."""
        inst = self._make_instrument()

        from loop_symphony.termination.evaluator import TerminationResult
        call_count = 0

        def mock_evaluate(findings, iteration, max_iter, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if iteration >= max_iter:
                return TerminationResult(
                    should_terminate=True,
                    outcome=Outcome.BOUNDED,
                    reason="Max iterations",
                )
            return TerminationResult(
                should_terminate=False, outcome=None, reason="Continue"
            )

        inst.termination.evaluate = mock_evaluate
        ctx = TaskContext(attachments=[SAMPLE_BASE64])
        result = await inst.execute("Describe", ctx)

        assert result.outcome == Outcome.BOUNDED
        assert result.iterations == 3

    @pytest.mark.asyncio
    async def test_calls_complete_with_images(self):
        """Verify complete_with_images is called (not complete for analysis)."""
        inst = self._make_instrument()
        ctx = TaskContext(attachments=[SAMPLE_BASE64])
        await inst.execute("Describe", ctx)

        inst.claude.complete_with_images.assert_called()
        # complete() is called for synthesis, but not for the analysis step
        call_args = inst.claude.complete_with_images.call_args
        images = call_args[0][1]  # second positional arg
        assert len(images) == 1
        assert images[0].source_type == "base64"

    @pytest.mark.asyncio
    async def test_multiple_images(self):
        """Multiple images are passed through to Claude."""
        inst = self._make_instrument()
        ctx = TaskContext(attachments=[SAMPLE_BASE64, SAMPLE_URL_JPG])
        await inst.execute("Compare these images", ctx)

        call_args = inst.claude.complete_with_images.call_args
        images = call_args[0][1]
        assert len(images) == 2

    @pytest.mark.asyncio
    async def test_checkpoint_emission(self):
        """Checkpoints are emitted at each iteration."""
        inst = self._make_instrument()
        checkpoint_fn = AsyncMock()
        ctx = TaskContext(attachments=[SAMPLE_BASE64], checkpoint_fn=checkpoint_fn)

        await inst.execute("Describe", ctx)

        checkpoint_fn.assert_called_once()
        call_args = checkpoint_fn.call_args
        assert call_args[0][0] == 1  # iteration number
        assert call_args[0][1] == "vision_analysis"  # phase

    @pytest.mark.asyncio
    async def test_checkpoint_failure_does_not_crash(self):
        """Checkpoint failure is logged but does not crash execution."""
        inst = self._make_instrument()
        checkpoint_fn = AsyncMock(side_effect=RuntimeError("DB down"))
        ctx = TaskContext(attachments=[SAMPLE_BASE64], checkpoint_fn=checkpoint_fn)

        result = await inst.execute("Describe", ctx)

        # Should still complete despite checkpoint failure
        assert result.outcome == Outcome.COMPLETE
        checkpoint_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_sources_consulted(self):
        """Sources includes claude_vision."""
        inst = self._make_instrument()
        ctx = TaskContext(attachments=[SAMPLE_BASE64])
        result = await inst.execute("Describe", ctx)

        assert "claude_vision" in result.sources_consulted

    @pytest.mark.asyncio
    async def test_json_parse_fallback(self):
        """Non-JSON response falls back to single finding."""
        inst = self._make_instrument()
        inst.claude.complete_with_images = AsyncMock(
            return_value="Just a plain text response about the image."
        )

        ctx = TaskContext(attachments=[SAMPLE_BASE64])
        result = await inst.execute("Describe", ctx)

        assert len(result.findings) >= 1
        assert "plain text response" in result.findings[0].content

    @pytest.mark.asyncio
    async def test_context_none_with_no_images(self):
        """context=None handled gracefully."""
        inst = self._make_instrument()
        result = await inst.execute("Describe", None)

        assert result.outcome == Outcome.BOUNDED
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# TestVisionRouting
# ---------------------------------------------------------------------------

class TestVisionRouting:
    """Tests for conductor routing to vision instrument."""

    @pytest.fixture
    def conductor(self):
        """Create a Conductor with mocked instruments."""
        from loop_symphony.manager.conductor import Conductor

        with patch("loop_symphony.manager.conductor.NoteInstrument"), \
             patch("loop_symphony.manager.conductor.ResearchInstrument"), \
             patch("loop_symphony.manager.conductor.SynthesisInstrument"), \
             patch("loop_symphony.manager.conductor.VisionInstrument"):
            cond = Conductor()
            yield cond

    @pytest.mark.asyncio
    async def test_routes_to_vision_with_base64_image(self, conductor):
        """Base64 image attachment routes to vision."""
        ctx = TaskContext(attachments=[SAMPLE_BASE64])
        request = TaskRequest(query="What is in this photo?", context=ctx)
        instrument = await conductor.analyze_and_route(request)
        assert instrument == "vision"

    @pytest.mark.asyncio
    async def test_routes_to_vision_with_url_image(self, conductor):
        """URL image attachment routes to vision."""
        ctx = TaskContext(attachments=[SAMPLE_URL_JPG])
        request = TaskRequest(query="Describe this image", context=ctx)
        instrument = await conductor.analyze_and_route(request)
        assert instrument == "vision"

    @pytest.mark.asyncio
    async def test_no_attachments_routes_normally(self, conductor):
        """No attachments routes to note/research as normal."""
        request = TaskRequest(query="Tell me about images of cats")
        instrument = await conductor.analyze_and_route(request)
        assert instrument != "vision"

    @pytest.mark.asyncio
    async def test_vision_keyword_without_image_not_vision(self, conductor):
        """Vision keywords without attachments do NOT route to vision."""
        request = TaskRequest(query="Describe this picture for me")
        instrument = await conductor.analyze_and_route(request)
        assert instrument != "vision"
