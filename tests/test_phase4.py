"""Tests for Phase 4: sandbox backends, telemetry, sub-agent dispatch."""

import json

import pytest

from crabkey.observability import Telemetry
from crabkey.orchestration.hook_dispatcher import HookDispatcher, HookEvent
from crabkey.safety.sandbox import Sandbox, SandboxConfig, SandboxUnavailable
from crabkey.tools.agent_tool import AgentDispatchTool
from crabkey.tools.base import ToolContext


# --------------------------------------------------------------------------- #
# Sandbox backends
# --------------------------------------------------------------------------- #

def test_sandbox_none_passes_command_through():
    sb = Sandbox(SandboxConfig(backend="none"))
    assert sb._wrap_command("echo hi", "/tmp") == "echo hi"


def test_sandbox_seatbelt_profile_scopes_writes_and_network(tmp_path):
    sb = Sandbox(SandboxConfig(backend="seatbelt", allowed_paths=[tmp_path], network_allowed=False))
    profile = sb._seatbelt_profile(tmp_path)
    assert "(deny file-write*)" in profile
    assert str(tmp_path.resolve()) in profile
    assert "(deny network*)" in profile


def test_sandbox_seatbelt_allows_network_when_configured(tmp_path):
    sb = Sandbox(SandboxConfig(backend="seatbelt", network_allowed=True))
    assert "(deny network*)" not in sb._seatbelt_profile(tmp_path)


def test_sandbox_docker_command_builds_mount_and_network(tmp_path, monkeypatch):
    import crabkey.safety.sandbox as sandbox_mod
    monkeypatch.setattr(sandbox_mod.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    sb = Sandbox(SandboxConfig(backend="docker", docker_image="alpine:3.20", network_allowed=False))
    cmd = sb._wrap_command("ls -la", tmp_path)
    assert "docker" in cmd and "run" in cmd and "--rm" in cmd
    assert "--network none" in cmd
    assert "alpine:3.20" in cmd
    assert str(tmp_path.resolve()) in cmd


def test_sandbox_unknown_backend_raises():
    sb = Sandbox(SandboxConfig(backend="bogus"))
    with pytest.raises(SandboxUnavailable):
        sb._wrap_command("ls", "/tmp")


def test_sandbox_missing_tool_raises(monkeypatch):
    import crabkey.safety.sandbox as sandbox_mod
    monkeypatch.setattr(sandbox_mod.shutil, "which", lambda name: None)
    sb = Sandbox(SandboxConfig(backend="docker"))
    with pytest.raises(SandboxUnavailable):
        sb._wrap_command("ls", "/tmp")


async def test_sandbox_none_runs_command(tmp_path):
    sb = Sandbox(SandboxConfig(backend="none", allowed_paths=[tmp_path]))
    code, out, err = await sb.run("echo hello", cwd=tmp_path)
    assert code == 0 and "hello" in out


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #

async def test_telemetry_records_events_and_jsonl(tmp_path):
    trace = tmp_path / "trace.jsonl"
    tel = Telemetry(trace_file=trace)
    dispatcher = HookDispatcher()
    tel.register(dispatcher)

    await dispatcher.fire(HookEvent.LOOP_START, {"goal": "do a thing", "thread_id": "t1"})
    await dispatcher.fire(HookEvent.PRE_TOOL, {"tool": "file.read"})
    await dispatcher.fire(HookEvent.POST_TOOL, {"tool": "file.read", "is_error": False})
    await dispatcher.fire(HookEvent.LOOP_END, {"thread_id": "t1"})

    assert tel.summary() == {"loop_start": 1, "pre_tool": 1, "post_tool": 1, "loop_end": 1}
    # JSONL file has one valid record per line, attrs are small/safe.
    lines = trace.read_text().strip().splitlines()
    assert len(lines) == 4
    first = json.loads(lines[0])
    assert first["event"] == "loop_start"
    assert first["attrs"]["goal"] == "do a thing"
    assert first["attrs"]["thread_id"] == "t1"


# --------------------------------------------------------------------------- #
# Sub-agent dispatch
# --------------------------------------------------------------------------- #

async def test_agent_dispatch_calls_runner():
    calls = []

    async def fake_dispatch(agent, task):
        calls.append((agent, task))
        return f"{agent} did: {task}"

    tool = AgentDispatchTool(fake_dispatch, ["reviewer", "tester"])
    out = await tool.run({"agent": "reviewer", "task": "check the diff"}, ToolContext(working_dir="."))
    assert out == "reviewer did: check the diff"
    assert calls == [("reviewer", "check the diff")]
    # Available agents surface in the schema + description.
    assert tool.parameters["properties"]["agent"]["enum"] == ["reviewer", "tester"]
    assert "reviewer" in tool.description


async def test_agent_dispatch_rejects_unknown_agent():
    async def fake_dispatch(agent, task):
        raise AssertionError("should not be called for unknown agent")

    tool = AgentDispatchTool(fake_dispatch, ["reviewer"])
    out = await tool.run({"agent": "ghost", "task": "x"}, ToolContext(working_dir="."))
    assert "unknown agent" in out and "reviewer" in out
