"""Tool protocol and manifest for Loop Library tool infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolManifest:
    """Immutable metadata descriptor for a tool."""

    name: str
    version: str
    description: str
    capabilities: frozenset[str]
    config_keys: frozenset[str]


@runtime_checkable
class Tool(Protocol):
    """Protocol that every Loop Library tool must satisfy."""

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    def manifest(self) -> ToolManifest: ...

    async def health_check(self) -> bool: ...
