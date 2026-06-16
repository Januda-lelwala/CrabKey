from .base import Tool, ToolContext, ToolRegistry
from .file_tool import FileEditTool, FileListTool, FileReadTool, FileWriteTool
from .shell_tool import ShellTool
from .web_tool import WebFetchTool, WebSearchTool
from .mcp_client import McpClient, McpServerConfig, McpProxyTool


def default_registry() -> ToolRegistry:
    """Return a ToolRegistry pre-loaded with the built-in tools."""
    reg = ToolRegistry()
    for tool in [FileReadTool(), FileWriteTool(), FileEditTool(), FileListTool(), ShellTool(), WebFetchTool()]:
        reg.register(tool)
    return reg


__all__ = [
    "Tool", "ToolContext", "ToolRegistry",
    "FileReadTool", "FileWriteTool", "FileEditTool", "FileListTool",
    "ShellTool",
    "WebFetchTool", "WebSearchTool",
    "McpClient", "McpServerConfig", "McpProxyTool",
    "default_registry",
]
