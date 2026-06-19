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

    PROTOCOL_VERSION = "2024-11-05"

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
        # MCP requires an initialize request/response handshake before any other
        # method, followed by an `initialized` notification.
        await self._send(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "crabkey", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        if self._proc is None:
            raise RuntimeError("McpClient not started — call start() first.")
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        self._proc.stdin.write((payload + "\n").encode())
        await self._proc.stdin.drain()

    async def _send(self, method: str, params: dict[str, Any]) -> Any:
        if self._proc is None:
            raise RuntimeError("McpClient not started — call start() first.")
        self._req_id += 1
        req_id = self._req_id
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        self._proc.stdin.write((payload + "\n").encode())
        await self._proc.stdin.drain()
        return await self._read_result(req_id)

    async def _read_result(self, req_id: int) -> Any:
        """Read stdout until the response matching *req_id* arrives.

        Server-initiated notifications and responses to other requests are
        skipped, and non-JSON lines (stray logging) are ignored, so a chatty
        server can't desynchronise the request/response pairing.
        """
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                stderr = b""
                if self._proc.stderr is not None:
                    stderr = await self._proc.stderr.read()
                raise RuntimeError(
                    f"MCP server {self.config.name!r} closed the connection. "
                    f"{stderr.decode(errors='replace').strip()}"
                )
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # not a JSON-RPC frame — ignore
            if msg.get("id") != req_id:
                continue  # a notification or another request's response
            if "error" in msg:
                raise RuntimeError(f"MCP error: {msg['error']}")
            return msg.get("result")

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


async def load_mcp_servers(
    servers: list[dict[str, Any]],
    registry: "ToolRegistry",
) -> list["McpClient"]:
    """Start each configured MCP server, register its tools, and return the clients.

    *servers* is the raw list from `ProjectConfig.mcp_servers` (TOML `[[mcp_servers]]`
    tables). The returned clients must be `stop()`-ped by the caller when done.
    A server that fails to start is skipped rather than aborting the whole run.
    """
    from .base import ToolRegistry  # noqa: F401  (imported for type clarity)

    clients: list[McpClient] = []
    for raw in servers:
        cfg = McpServerConfig(
            name=raw["name"],
            command=raw["command"],
            args=list(raw.get("args", [])),
            env=raw.get("env"),
        )
        client = McpClient(cfg)
        try:
            await client.start()
            for tool in await client.discover():
                registry.register(tool)
        except Exception:
            await client.stop()
            continue
        clients.append(client)
    return clients
