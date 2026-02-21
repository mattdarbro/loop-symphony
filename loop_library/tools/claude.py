"""Anthropic Claude API wrapper with retry logic and vision support."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass

from anthropic import AsyncAnthropic, APIError, RateLimitError

from loop_library.tools.base import ToolManifest


@dataclass(frozen=True)
class ImageInput:
    """A single image for multimodal Claude requests."""

    source_type: str  # "base64" or "url"
    media_type: str   # "image/jpeg", "image/png", "image/gif", "image/webp"
    data: str         # base64 string (no data URI prefix) or URL

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Wrapper for Anthropic Claude API with retry logic."""

    name: str = "claude"
    capabilities: frozenset[str] = frozenset({"reasoning", "synthesis", "analysis", "vision"})

    def manifest(self) -> ToolManifest:
        """Return static metadata about this tool."""
        return ToolManifest(
            name=self.name,
            version="0.1.0",
            description="Anthropic Claude API wrapper with retry logic and vision support",
            capabilities=self.capabilities,
            config_keys=frozenset({"ANTHROPIC_API_KEY", "CLAUDE_MODEL", "CLAUDE_MAX_TOKENS"}),
        )

    async def health_check(self) -> bool:
        """Check connectivity to the Claude API with a minimal request."""
        try:
            await self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        _api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = AsyncAnthropic(api_key=_api_key)
        self.model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        self.max_tokens = max_tokens or int(os.environ.get("CLAUDE_MAX_TOKENS", "4096"))
        self.max_retries = 3
        self.base_delay = 1.0

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a completion from Claude."""
        messages = [{"role": "user", "content": prompt}]

        for attempt in range(self.max_retries):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    system=system or "",
                    messages=messages,
                )
                return response.content[0].text

            except RateLimitError as e:
                if attempt == self.max_retries - 1:
                    raise
                delay = self.base_delay * (2**attempt)
                logger.warning(f"Rate limited, retrying in {delay}s: {e}")
                await asyncio.sleep(delay)

            except APIError as e:
                if attempt == self.max_retries - 1:
                    raise
                if e.status_code and e.status_code >= 500:
                    delay = self.base_delay * (2**attempt)
                    logger.warning(f"Server error, retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    raise

        raise APIError("Max retries exceeded")

    async def complete_with_images(
        self,
        prompt: str,
        images: list[ImageInput],
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a completion from Claude with image inputs."""
        content: list[dict] = []
        for image in images:
            if image.source_type == "base64":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.data,
                    },
                })
            elif image.source_type == "url":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": image.data,
                    },
                })
        content.append({"type": "text", "text": prompt})

        messages = [{"role": "user", "content": content}]

        for attempt in range(self.max_retries):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    system=system or "",
                    messages=messages,
                )
                return response.content[0].text

            except RateLimitError as e:
                if attempt == self.max_retries - 1:
                    raise
                delay = self.base_delay * (2**attempt)
                logger.warning(f"Rate limited, retrying in {delay}s: {e}")
                await asyncio.sleep(delay)

            except APIError as e:
                if attempt == self.max_retries - 1:
                    raise
                if e.status_code and e.status_code >= 500:
                    delay = self.base_delay * (2**attempt)
                    logger.warning(f"Server error, retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    raise

        raise APIError("Max retries exceeded")

    async def analyze(
        self,
        content: str,
        instruction: str,
        system: str | None = None,
    ) -> str:
        """Analyze content with a specific instruction."""
        prompt = f"{instruction}\n\nContent:\n{content}"
        return await self.complete(prompt, system=system)

    async def synthesize(
        self,
        findings: list[str],
        query: str,
    ) -> str:
        """Synthesize multiple findings into a coherent summary."""
        findings_text = "\n\n".join(f"Finding {i+1}:\n{f}" for i, f in enumerate(findings))

        system = (
            "You are a research synthesizer. Your job is to combine multiple findings "
            "into a coherent, accurate summary that directly addresses the user's query. "
            "Be concise but comprehensive. Cite sources when available."
        )

        prompt = f"""Original Query: {query}

Findings:
{findings_text}

Synthesize these findings into a clear, direct answer to the query."""

        return await self.complete(prompt, system=system)

    @staticmethod
    def _parse_json_response(text: str) -> dict | None:
        """Extract and parse JSON from a Claude response."""
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            pass

        code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    async def synthesize_with_analysis(
        self,
        findings: list[str],
        query: str,
    ) -> dict:
        """Synthesize findings and detect contradictions in a single call."""
        findings_text = "\n\n".join(
            f"Finding {i+1}:\n{f}" for i, f in enumerate(findings)
        )

        system = (
            "You are a research synthesizer. Your job is to combine multiple findings "
            "into a coherent, accurate summary that directly addresses the user's query. "
            "Be concise but comprehensive. Cite sources when available.\n\n"
            "IMPORTANT: You must also check whether the findings contradict each other. "
            "Respond with a JSON object (no markdown wrapping) with these exact keys:\n"
            '- "summary": your synthesized summary text\n'
            '- "has_contradictions": true or false\n'
            '- "contradiction_hint": if has_contradictions is true, briefly describe '
            "what the findings disagree about; otherwise null"
        )

        prompt = f"""Original Query: {query}

Findings:
{findings_text}

Synthesize these findings and check for contradictions. Respond with the JSON object only."""

        response = await self.complete(prompt, system=system)

        parsed = self._parse_json_response(response)
        if parsed and "summary" in parsed:
            return {
                "summary": parsed["summary"],
                "has_contradictions": bool(parsed.get("has_contradictions", False)),
                "contradiction_hint": parsed.get("contradiction_hint"),
            }

        return {
            "summary": response,
            "has_contradictions": False,
            "contradiction_hint": None,
        }

    async def analyze_discrepancy(
        self,
        findings: list[str],
        query: str,
        contradiction_hint: str,
    ) -> dict:
        """Analyze a detected contradiction in depth."""
        findings_text = "\n\n".join(
            f"Finding {i+1}:\n{f}" for i, f in enumerate(findings)
        )

        system = (
            "You are a research analyst specializing in identifying and characterizing "
            "conflicting information. Analyze the contradiction described below and "
            "respond with a JSON object (no markdown wrapping) with these exact keys:\n"
            '- "description": a clear description of the discrepancy\n'
            '- "severity": one of "minor", "moderate", or "significant"\n'
            '- "conflicting_claims": a list of the specific claims that conflict\n'
            '- "suggested_refinements": a list of 2-3 follow-up queries that could '
            "help resolve the contradiction"
        )

        prompt = f"""Original Query: {query}

Contradiction detected: {contradiction_hint}

Findings:
{findings_text}

Analyze this contradiction in depth. Respond with the JSON object only."""

        response = await self.complete(prompt, system=system)

        parsed = self._parse_json_response(response)
        if parsed and "description" in parsed:
            return {
                "description": parsed["description"],
                "severity": parsed.get("severity", "moderate"),
                "conflicting_claims": parsed.get("conflicting_claims", []),
                "suggested_refinements": parsed.get("suggested_refinements", []),
            }

        return {
            "description": contradiction_hint,
            "severity": "moderate",
            "conflicting_claims": [],
            "suggested_refinements": [],
        }
