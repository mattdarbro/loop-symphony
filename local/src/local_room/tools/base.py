"""Tool protocol for Local Room.

Matches the server's Tool protocol for compatibility.
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolManifest(BaseModel):
    """Describes a tool's identity and capabilities."""

    model_config = {"frozen": True}

    name: str
    version: str
    description: str
    capabilities: frozenset[str] = Field(default_factory=frozenset)


@runtime_checkable
class Tool(Protocol):
    """Protocol that all tools must implement."""

    @property
    def name(self) -> str:
        """Unique identifier for this tool."""
        ...

    @property
    def manifest(self) -> ToolManifest:
        """Return the tool's manifest."""
        ...

    async def health_check(self) -> dict[str, Any]:
        """Check if the tool is healthy and operational.

        Returns:
            Dict with at least {"healthy": bool}
        """
        ...
