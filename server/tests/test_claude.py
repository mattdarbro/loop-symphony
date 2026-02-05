"""Tests for Claude client JSON parsing and analysis methods."""

import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from loop_symphony.tools.claude import ClaudeClient


@pytest.fixture
def mock_settings():
    """Mock settings for tests."""
    with patch("loop_symphony.tools.claude.get_settings") as mock:
        settings = MagicMock()
        settings.anthropic_api_key = "test-key"
        settings.claude_model = "test-model"
        settings.claude_max_tokens = 1024
        mock.return_value = settings
        yield settings


@pytest.fixture
def claude_client(mock_settings):
    """Create a Claude client with mocked settings."""
    with patch("loop_symphony.tools.claude.AsyncAnthropic"):
        client = ClaudeClient()
        yield client


class TestParseJsonResponse:
    """Tests for _parse_json_response static method."""

    def test_parses_well_formed_json(self):
        """Test parsing a well-formed JSON response."""
        text = json.dumps({
            "summary": "Coffee has mixed effects.",
            "has_contradictions": True,
            "contradiction_hint": "Sources disagree on cardiovascular effects",
        })

        result = ClaudeClient._parse_json_response(text)

        assert result is not None
        assert result["summary"] == "Coffee has mixed effects."
        assert result["has_contradictions"] is True
        assert result["contradiction_hint"] == "Sources disagree on cardiovascular effects"

    def test_handles_json_in_markdown_code_blocks(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        text = """Here is my analysis:

```json
{
    "summary": "The population of Tokyo is approximately 14 million.",
    "has_contradictions": false,
    "contradiction_hint": null
}
```"""

        result = ClaudeClient._parse_json_response(text)

        assert result is not None
        assert result["summary"] == "The population of Tokyo is approximately 14 million."
        assert result["has_contradictions"] is False

    def test_falls_back_on_plain_text(self):
        """Test that plain text (no JSON) returns None."""
        text = "This is just a plain text summary with no JSON structure at all."

        result = ClaudeClient._parse_json_response(text)

        assert result is None


class TestSynthesizeWithAnalysis:
    """Tests for synthesize_with_analysis method."""

    @pytest.mark.asyncio
    async def test_parses_structured_response(self, claude_client):
        """Test synthesize_with_analysis parses well-formed JSON."""
        claude_client.complete = AsyncMock(return_value=json.dumps({
            "summary": "Research shows mixed results.",
            "has_contradictions": True,
            "contradiction_hint": "Study A says X, Study B says Y",
        }))

        result = await claude_client.synthesize_with_analysis(
            ["Finding 1", "Finding 2"], "test query"
        )

        assert result["summary"] == "Research shows mixed results."
        assert result["has_contradictions"] is True
        assert result["contradiction_hint"] == "Study A says X, Study B says Y"

    @pytest.mark.asyncio
    async def test_falls_back_on_plain_text(self, claude_client):
        """Test fallback when Claude returns plain text instead of JSON."""
        claude_client.complete = AsyncMock(
            return_value="Just a plain summary with no JSON."
        )

        result = await claude_client.synthesize_with_analysis(
            ["Finding 1"], "test query"
        )

        assert result["summary"] == "Just a plain summary with no JSON."
        assert result["has_contradictions"] is False
        assert result["contradiction_hint"] is None


class TestAnalyzeDiscrepancy:
    """Tests for analyze_discrepancy method."""

    @pytest.mark.asyncio
    async def test_parses_structured_response(self, claude_client):
        """Test analyze_discrepancy parses well-formed JSON."""
        claude_client.complete = AsyncMock(return_value=json.dumps({
            "description": "Sources disagree on coffee's cardiovascular effects",
            "severity": "significant",
            "conflicting_claims": [
                "Coffee increases heart disease risk",
                "Coffee reduces heart disease risk",
            ],
            "suggested_refinements": [
                "Research coffee effects on specific heart conditions",
                "Look for meta-analyses on coffee and cardiovascular health",
            ],
        }))

        result = await claude_client.analyze_discrepancy(
            ["Finding 1", "Finding 2"],
            "Is coffee healthy?",
            "Disagreement on cardiovascular effects",
        )

        assert result["description"] == "Sources disagree on coffee's cardiovascular effects"
        assert result["severity"] == "significant"
        assert len(result["conflicting_claims"]) == 2
        assert len(result["suggested_refinements"]) == 2

    @pytest.mark.asyncio
    async def test_handles_malformed_response(self, claude_client):
        """Test fallback when Claude returns non-JSON response."""
        claude_client.complete = AsyncMock(
            return_value="I found some contradictions but can't format as JSON."
        )

        result = await claude_client.analyze_discrepancy(
            ["Finding 1"],
            "test query",
            "Some contradiction hint",
        )

        # Should fall back to using the hint as description
        assert result["description"] == "Some contradiction hint"
        assert result["severity"] == "moderate"
        assert result["conflicting_claims"] == []
        assert result["suggested_refinements"] == []
