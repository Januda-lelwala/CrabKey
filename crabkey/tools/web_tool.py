from __future__ import annotations

import os
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
    """Search the web via whichever provider has an API key configured.

    Supported, in priority order: Tavily (TAVILY_API_KEY), Brave
    (BRAVE_API_KEY / BRAVE_SEARCH_API_KEY), and Serper (SERPER_API_KEY).
    """

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
        # Explicit override; otherwise resolved from the environment per backend.
        self._api_key = api_key

    @staticmethod
    def _format(results: list[dict[str, str]]) -> str:
        if not results:
            return "No results."
        return "\n\n".join(
            f"{r['title']}\n{r['url']}\n{r['snippet']}".strip() for r in results
        )

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("Install 'httpx' to use WebSearchTool.") from exc

        query = arguments["query"]
        num = int(arguments.get("num_results", 5))

        tavily = self._api_key or os.environ.get("TAVILY_API_KEY")
        brave = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
        serper = os.environ.get("SERPER_API_KEY")

        async with httpx.AsyncClient(timeout=20) as client:
            if tavily:
                results = await self._tavily(client, tavily, query, num)
            elif brave:
                results = await self._brave(client, brave, query, num)
            elif serper:
                results = await self._serper(client, serper, query, num)
            else:
                raise RuntimeError(
                    "No web search backend configured. Set one of TAVILY_API_KEY, "
                    "BRAVE_API_KEY, or SERPER_API_KEY."
                )
        return self._format(results)

    async def _tavily(self, client, key, query, num) -> list[dict[str, str]]:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": num},
        )
        resp.raise_for_status()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in resp.json().get("results", [])[:num]
        ]

    async def _brave(self, client, key, query, num) -> list[dict[str, str]]:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": num},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        resp.raise_for_status()
        web = resp.json().get("web", {}).get("results", [])
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
            for r in web[:num]
        ]

    async def _serper(self, client, key, query, num) -> list[dict[str, str]]:
        resp = await client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": num},
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return [
            {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
            for r in resp.json().get("organic", [])[:num]
        ]
