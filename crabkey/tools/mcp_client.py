from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .base import Tool, ToolContext, ToolSchema


@dataclass
class McpServerConfig:
    name: str
    command: str          # e.g. "npx"
    args: list[str]       # e.g. ["-y", "@modelcontextprotocol/server-github"]
    env: dict[str, str] | None = None


class McpProxyTool(Tool):
    """
    Proxies a single MCP tool call to a running MCP server process.
    One McpProxyTool instance is created per tool exposed by the server.
    """

    def __init__(self, tool_name: str, tool_description: str, tool_params: dict[str, Any], server: "McpClient") -> None:
        self._name = tool_name
        self._description = tool_description
        self._parameters = tool_params
        self._server = server

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        return await self._server.call_tool(self._name, arguments)


class McpClient:
    """
    Spawns and communicates with an MCP server over JSON-RPC stdio.
    Call `discover()` to get a list of McpProxyTool instances to register.
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._proc = None
        self._req_id = 0

    async def start(self) -> None:
        import asyncio
        import os

        env = dict(os.environ)
        if self.config.env:
            env.update(self.config.env)
        self._proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def _send(self, method: str, params: dict[str, Any]) -> Any:
        if self._proc is None:
            raise RuntimeError("McpClient not started — call start() first.")
        self._req_id += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params})
        self._proc.stdin.write((payload + "\n").encode())
        await self._proc.stdin.drain()
        line = await self._proc.stdout.readline()
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(f"MCP error: {resp['error']}")
        return resp.get("result")

    async def discover(self) -> list[McpProxyTool]:
        result = await self._send("tools/list", {})
        tools = []
        for t in result.get("tools", []):
            tools.append(McpProxyTool(
                tool_name=t["name"],
                tool_description=t.get("description", ""),
                tool_params=t.get("inputSchema", {"type": "object", "properties": {}}),
                server=self,
            ))
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._send("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        parts = [c["text"] for c in content if c.get("type") == "text"]
        return "\n".join(parts)

    async def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            await self._proc.wait()
            self._proc = None
