"""External integrations and API wrappers."""

from loop_library.tools.base import Tool, ToolManifest
from loop_library.tools.claude import ClaudeClient, ImageInput
from loop_library.tools.registry import CapabilityError, ToolRegistry
from loop_library.tools.tavily import TavilyClient

__all__ = [
    "CapabilityError",
    "ClaudeClient",
    "ImageInput",
    "TavilyClient",
    "Tool",
    "ToolManifest",
    "ToolRegistry",
]
