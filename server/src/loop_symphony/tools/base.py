"""Tool protocol and manifest for Loop Symphony tool infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolManifest:
    """Immutable metadata descriptor for a tool.

    Attributes:
        name: Stable unique identifier (e.g. "claude", "tavily").
        version: Wrapper version string.
        description: Human-readable summary of the tool.
        capabilities: What this tool provides (e.g. "reasoning", "web_search").
        config_keys: Environment variables this tool requires (for diagnostics).
    """

    name: str
    version: str
    description: str
    capabilities: frozenset[str]
    config_keys: frozenset[str]


@runtime_checkable
class Tool(Protocol):
    """Protocol that every Loop Symphony tool must satisfy.

    Tools keep their domain-specific APIs (complete(), search(), etc.).
    This protocol is for infrastructure: registry, health checks, metadata.
    """

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    def manifest(self) -> ToolManifest: ...

    async def health_check(self) -> bool: ...
