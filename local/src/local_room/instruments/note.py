"""Local Note instrument using Ollama.

Single-cycle, quick responses for simple queries.
Runs entirely on the local machine.
"""

import logging
from datetime import datetime, UTC
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from local_room.tools.ollama import OllamaClient, OllamaError

logger = logging.getLogger(__name__)


class Finding(BaseModel):
    """A single finding from an instrument."""

    content: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str | None = None


class InstrumentResult(BaseModel):
    """Result from running an instrument."""

    outcome: str  # COMPLETE, BOUNDED, INCONCLUSIVE
    findings: list[Finding]
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    iterations: int = 1
    duration_ms: int = 0
    instrument: str = "note"


class LocalNoteInstrument:
    """Local Note instrument for simple queries.

    Uses Ollama for local LLM inference.
    Single-cycle: one prompt, one response.
    """

    def __init__(self, ollama: OllamaClient) -> None:
        """Initialize with Ollama client.

        Args:
            ollama: The Ollama client to use
        """
        self._ollama = ollama
        self._name = "local_note"

    @property
    def name(self) -> str:
        return self._name

    async def execute(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> InstrumentResult:
        """Execute the note instrument.

        Args:
            query: The user's question
            context: Optional context (conversation_summary, etc.)

        Returns:
            InstrumentResult with findings and summary
        """
        start_time = datetime.now(UTC)

        # Build system prompt
        system = self._build_system_prompt(context)

        try:
            # Get response from Ollama
            response = await self._ollama.complete(
                prompt=query,
                system=system,
                temperature=0.7,
            )

            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            # Parse response
            finding = Finding(
                content=response.strip(),
                confidence=0.85,  # Local models get slightly lower default confidence
                source=f"local:{self._ollama.model}",
            )

            return InstrumentResult(
                outcome="COMPLETE",
                findings=[finding],
                summary=response.strip(),
                confidence=0.85,
                iterations=1,
                duration_ms=duration_ms,
                instrument=self._name,
            )

        except OllamaError as e:
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            logger.error(f"Ollama error: {e}")

            return InstrumentResult(
                outcome="INCONCLUSIVE",
                findings=[],
                summary=f"Local LLM error: {e}",
                confidence=0.0,
                iterations=1,
                duration_ms=duration_ms,
                instrument=self._name,
            )

    def _build_system_prompt(self, context: dict[str, Any] | None) -> str:
        """Build the system prompt."""
        base = (
            "You are a helpful assistant running locally. "
            "Provide clear, concise answers. "
            "If you're not sure about something, say so."
        )

        if context and context.get("conversation_summary"):
            base += f"\n\nPrevious context: {context['conversation_summary']}"

        return base

    async def health_check(self) -> dict[str, Any]:
        """Check if the instrument is healthy."""
        ollama_health = await self._ollama.health_check()
        return {
            "healthy": ollama_health.get("healthy", False),
            "instrument": self._name,
            "ollama": ollama_health,
        }
