"""Tool registry for capability-based tool resolution."""

import logging

from loop_library.tools.base import Tool

logger = logging.getLogger(__name__)


class CapabilityError(Exception):
    """Raised when required capabilities cannot be resolved."""


class ToolRegistry:
    """Central registry that maps capabilities to tool instances."""

    def __init__(self) -> None:
        self._by_name: dict[str, Tool] = {}
        self._by_capability: dict[str, list[Tool]] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        if tool.name in self._by_name:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._by_name[tool.name] = tool
        for cap in tool.capabilities:
            self._by_capability.setdefault(cap, []).append(tool)

    def get_by_name(self, name: str) -> Tool | None:
        return self._by_name.get(name)

    def get_by_capability(self, capability: str) -> Tool | None:
        tools = self._by_capability.get(capability, [])
        return tools[0] if tools else None

    def get_all(self) -> list[Tool]:
        return list(self._by_name.values())

    def resolve(
        self,
        required: frozenset[str],
        optional: frozenset[str] = frozenset(),
    ) -> dict[str, Tool]:
        """Resolve capabilities to tool instances."""
        result: dict[str, Tool] = {}
        missing: list[str] = []

        for cap in sorted(required):
            tool = self.get_by_capability(cap)
            if tool is None:
                missing.append(cap)
            else:
                result[cap] = tool

        if missing:
            raise CapabilityError(f"Missing required capabilities: {missing}")

        for cap in sorted(optional):
            tool = self.get_by_capability(cap)
            if tool is not None:
                result[cap] = tool
            else:
                logger.warning("Optional capability '%s' not available", cap)

        return result

    async def health_check_all(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, tool in self._by_name.items():
            results[name] = await tool.health_check()
        return results

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: str) -> bool:
        return name in self._by_name
