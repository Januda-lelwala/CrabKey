from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext


class WebFetchTool(Tool):
    name = "web.fetch"
    description = "Fetch the text content of a URL. Returns the response body."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "headers": {"type": "object", "description": "Optional HTTP headers."},
        },
        "required": ["url"],
    }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("Install 'httpx' to use WebFetchTool.") from exc
        headers = arguments.get("headers", {})
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(arguments["url"], headers=headers)
            resp.raise_for_status()
            return resp.text


class WebSearchTool(Tool):
    """Stub: wire to a real search API (Brave, SerpAPI, etc.) in production."""

    name = "web.search"
    description = "Search the web and return a list of results (title, url, snippet)."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "num_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        raise NotImplementedError(
            "WebSearchTool requires a search API key. "
            "Subclass this and implement run() with your preferred provider."
        )
