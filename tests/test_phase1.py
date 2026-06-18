"""Tests for Phase 1 integration work:

- PermissionBroker interactive approval (on_ask callback)
- LoopEngine firing lifecycle hooks and creating checkpoints
- McpClient JSON-RPC initialize handshake + robust read loop
"""

import json

import pytest

from crabkey.mal.message import CompletionResponse, Message, Role, ToolCall, Usage
from crabkey.mal.provider import ModelConfig, ToolSchema
from crabkey.orchestration.hook_dispatcher import HookDispatcher, HookEvent
from crabkey.orchestration.loop_engine import (
    LoopConfig,
    LoopEngine,
    representative_arg,
)
from crabkey.safety.permission_broker import (
    ApprovalDecision,
    Permission,
    PermissionBroker,
    PermissionLevel,
)
from crabkey.tools.base import Tool, ToolContext, ToolRegistry
from crabkey.tools.mcp_client import McpClient, McpServerConfig


# --------------------------------------------------------------------------- #
# PermissionBroker interactive approval
# --------------------------------------------------------------------------- #

class TestBrokerApproval:
    def setup_method(self):
        self.broker = PermissionBroker()

    def test_ask_without_approver_still_raises(self):
        # Backwards compatible: no on_ask → conservative refusal.
        with pytest.raises(PermissionError, match="confirmation"):
            self.broker.require("shell.run")

    def test_allow_once_does_not_persist(self):
        calls = []

        def approver(tool, arg):
            calls.append((tool, arg))
            return ApprovalDecision.ALLOW_ONCE

        self.broker.require("shell.run", "ls", on_ask=approver)
        # Asked again → still ASK, so approver is consulted a second time.
        self.broker.require("shell.run", "ls", on_ask=approver)
        assert len(calls) == 2

    def test_allow_always_adds_rule(self):
        def approver(tool, arg):
            return ApprovalDecision.ALLOW_ALWAYS

        self.broker.require("shell.run", "ls", on_ask=approver)
        # Now a session ALLOW rule exists, so no further prompting.
        assert self.broker.check("shell.run", "ls") == PermissionLevel.ALLOW

    def test_deny_raises(self):
        def approver(tool, arg):
            return ApprovalDecision.DENY

        with pytest.raises(PermissionError, match="denied by user"):
            self.broker.require("shell.run", "rm -rf /", on_ask=approver)


def test_representative_arg_prefers_command_then_path():
    assert representative_arg("shell.run", {"command": "ls", "path": "x"}) == "ls"
    assert representative_arg("file.edit", {"path": "a.py"}) == "a.py"
    assert representative_arg("file.read", {}) is None


# --------------------------------------------------------------------------- #
# LoopEngine hooks + checkpoint
# --------------------------------------------------------------------------- #

class _NoopTool(Tool):
    name = "file.write"
    description = "write"
    parameters = {"type": "object", "properties": {}}

    async def run(self, arguments, ctx: ToolContext) -> str:
        return "ok"


class _FakeAssembler:
    async def build(self, history, base_system=None, **kwargs):
        return list(history)


class _FakeDb:
    async def log_cost(self, *args, **kwargs):
        return None


class _ScriptedProvider:
    """Returns a tool call on the first turn, then ends the turn."""

    def __init__(self):
        self._turn = 0
        self.name = "fake"

    async def complete(self, messages, config, tools=None):
        self._turn += 1
        if self._turn == 1:
            msg = Message(
                role=Role.ASSISTANT,
                content="working",
                tool_calls=[ToolCall(id="t1", name="file.write", arguments={"path": "a.txt"})],
            )
            return CompletionResponse(message=msg, usage=Usage(), model="fake", stop_reason="tool_use")
        msg = Message(role=Role.ASSISTANT, content="done")
        return CompletionResponse(message=msg, usage=Usage(), model="fake", stop_reason="end_turn")


class _RecordingCheckpoint:
    def __init__(self):
        self.labels = []

    async def create(self, label):
        self.labels.append(label)
        return None


def _make_loop(**kwargs):
    tools = ToolRegistry()
    tools.register(_NoopTool())
    broker = PermissionBroker()
    broker.add_rule(Permission(tool="*", level=PermissionLevel.ALLOW))
    return LoopEngine(
        provider=_ScriptedProvider(),
        tools=tools,
        assembler=_FakeAssembler(),
        db=_FakeDb(),
        broker=broker,
        config=LoopConfig(max_iterations=5),
        **kwargs,
    )


async def test_loop_fires_lifecycle_hooks():
    hooks = HookDispatcher()
    seen: list[HookEvent] = []

    async def handler(event, payload):
        seen.append(event)

    for e in HookEvent:
        hooks.on(e, handler)

    loop = _make_loop(hooks=hooks)
    await loop.run(goal="g", thread_id="th", model_config=ModelConfig(model="fake"), working_dir="/tmp")

    assert seen[0] == HookEvent.LOOP_START
    assert seen[-1] == HookEvent.LOOP_END
    assert HookEvent.PRE_TOOL in seen and HookEvent.POST_TOOL in seen
    assert HookEvent.PRE_TURN in seen and HookEvent.POST_TURN in seen


async def test_loop_checkpoints_once_before_destructive_tool():
    ckpt = _RecordingCheckpoint()
    loop = _make_loop(checkpoint=ckpt)
    await loop.run(goal="g", thread_id="th", model_config=ModelConfig(model="fake"), working_dir="/tmp")
    # file.write is destructive → exactly one checkpoint for the turn.
    assert len(ckpt.labels) == 1
    assert "file.write" in ckpt.labels[0]


# --------------------------------------------------------------------------- #
# McpClient handshake + robust read loop
# --------------------------------------------------------------------------- #

class _FakeStream:
    """Minimal stand-in for an asyncio StreamReader/Writer pair."""

    def __init__(self, lines):
        self._lines = list(lines)

    # writer side — swallow everything
    def write(self, data):
        pass

    async def drain(self):
        pass

    # reader side
    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self):
        data = b"".join(self._lines)
        self._lines = []
        return data


async def test_mcp_read_result_skips_notifications_and_mismatched_ids():
    client = McpClient(McpServerConfig(name="x", command="true", args=[]))
    client._proc = type("P", (), {})()
    # A server notification, a stray non-JSON line, an unrelated response, then ours.
    client._proc.stdout = _FakeStream([
        json.dumps({"jsonrpc": "2.0", "method": "notifications/log", "params": {}}).encode() + b"\n",
        b"not json at all\n",
        json.dumps({"jsonrpc": "2.0", "id": 99, "result": {"wrong": True}}).encode() + b"\n",
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}).encode() + b"\n",
    ])
    client._proc.stderr = _FakeStream([])
    result = await client._read_result(1)
    assert result == {"ok": True}


async def test_mcp_read_result_raises_on_closed_connection():
    client = McpClient(McpServerConfig(name="x", command="true", args=[]))
    client._proc = type("P", (), {})()
    client._proc.stdout = _FakeStream([])  # immediate EOF
    client._proc.stderr = _FakeStream([b"boom\n"])
    with pytest.raises(RuntimeError, match="closed the connection"):
        await client._read_result(1)


async def test_mcp_send_raises_when_not_started():
    client = McpClient(McpServerConfig(name="x", command="true", args=[]))
    with pytest.raises(RuntimeError, match="not started"):
        await client._send("ping", {})
