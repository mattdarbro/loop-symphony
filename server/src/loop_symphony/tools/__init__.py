"""External integrations and API wrappers."""

from loop_symphony.tools.base import Tool, ToolManifest
from loop_symphony.tools.claude import ClaudeClient, ImageInput
from loop_symphony.tools.registry import CapabilityError, ToolRegistry
from loop_symphony.tools.tavily import TavilyClient

__all__ = [
    "CapabilityError",
    "ClaudeClient",
    "ImageInput",
    "TavilyClient",
    "Tool",
    "ToolManifest",
    "ToolRegistry",
]
