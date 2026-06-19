from .base import Tool, ToolContext, ToolRegistry
from .file_tool import FileEditTool, FileListTool, FileReadTool, FileWriteTool
from .shell_tool import ShellTool
from .search_tool import GlobTool, GrepTool
from .memory_tool import SaveMemoryTool
from .web_tool import WebFetchTool, WebSearchTool
from .mcp_client import McpClient, McpServerConfig, McpProxyTool, load_mcp_servers


def default_registry() -> ToolRegistry:
    """Return a ToolRegistry pre-loaded with the built-in tools."""
    reg = ToolRegistry()
    for tool in [
        FileReadTool(), FileWriteTool(), FileEditTool(), FileListTool(),
        GrepTool(), GlobTool(),
        ShellTool(), WebFetchTool(), WebSearchTool(),
    ]:
        reg.register(tool)
    return reg


__all__ = [
    "Tool", "ToolContext", "ToolRegistry",
    "FileReadTool", "FileWriteTool", "FileEditTool", "FileListTool",
    "GrepTool", "GlobTool", "SaveMemoryTool",
    "ShellTool",
    "WebFetchTool", "WebSearchTool",
    "McpClient", "McpServerConfig", "McpProxyTool", "load_mcp_servers",
    "default_registry",
]
