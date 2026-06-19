"""Regression tests for bugs found by running the agent end-to-end:

1. Tool names with dots (file.read) violate the OpenAI/Anthropic function-name
   pattern ^[a-zA-Z0-9_-]+$ and must be sanitized on the wire, then mapped back.
2. (Covered by live run) `crabkey run` must create a session before forking a
   thread; and headless JSON must bypass Rich. Those are wiring-level and are
   exercised by the live smoke test rather than unit tests.
"""

from crabkey.mal.message import Message, Role, ToolCall, ToolResult
from crabkey.mal.plugin_provider import (
    PluginModelProvider,
    _messages_to_openai_wire,
    _remap_tool_call_names,
    _sanitize_tool_name,
)
from crabkey.mal.provider import ToolSchema


def test_sanitize_tool_name_replaces_dots():
    assert _sanitize_tool_name("file.read") == "file_read"
    assert _sanitize_tool_name("search.grep") == "search_grep"
    assert _sanitize_tool_name("already_ok-1") == "already_ok-1"


def test_tool_schemas_to_wire_sanitizes_names():
    provider = PluginModelProvider.__new__(PluginModelProvider)  # no network init
    wire = PluginModelProvider._tool_schemas_to_wire(
        provider, [ToolSchema(name="file.write", description="d", parameters={})]
    )
    assert wire[0]["function"]["name"] == "file_write"


def test_name_map_and_remap_round_trip():
    tools = [ToolSchema(name="file.read", description="", parameters={})]
    name_map = PluginModelProvider._name_map(tools)
    assert name_map == {"file_read": "file.read"}

    # The model returns the sanitized name; we must restore the dotted original.
    calls = [ToolCall(id="1", name="file_read", arguments={})]
    _remap_tool_call_names(calls, name_map)
    assert calls[0].name == "file.read"


def test_remap_leaves_unknown_names_untouched():
    calls = [ToolCall(id="1", name="mystery_tool", arguments={})]
    _remap_tool_call_names(calls, {"file_read": "file.read"})
    assert calls[0].name == "mystery_tool"


async def test_loop_run_continues_passed_history():
    """The TUI passes a persistent history list across turns; run() must reuse
    and extend it rather than starting fresh."""
    from crabkey.mal.message import CompletionResponse, Message, Role, Usage
    from crabkey.mal.provider import ModelConfig
    from crabkey.orchestration.loop_engine import LoopConfig, LoopEngine
    from crabkey.safety.permission_broker import Permission, PermissionBroker, PermissionLevel
    from crabkey.tools.base import ToolRegistry

    class _Provider:
        name = "fake"

        async def complete(self, messages, config, tools=None):
            return CompletionResponse(
                message=Message(role=Role.ASSISTANT, content="ok"),
                usage=Usage(), model="fake", stop_reason="end_turn",
            )

    class _Assembler:
        async def build(self, history, base_system=None, **kw):
            return list(history)

    class _Db:
        async def log_cost(self, *a, **k):
            return None

    broker = PermissionBroker()
    broker.add_rule(Permission(tool="*", level=PermissionLevel.ALLOW))
    loop = LoopEngine(
        provider=_Provider(), tools=ToolRegistry(), assembler=_Assembler(),
        db=_Db(), broker=broker, config=LoopConfig(max_iterations=2, stream=False),
    )

    prior = [
        Message(role=Role.USER, content="first question"),
        Message(role=Role.ASSISTANT, content="first answer"),
    ]
    returned = await loop.run(
        goal="second question", thread_id="t", model_config=ModelConfig(model="fake"),
        working_dir="/tmp", history=prior,
    )
    # Same list object, prior turns preserved, new turn appended.
    assert returned is prior
    assert prior[0].content == "first question"
    assert any(m.role == Role.USER and m.content == "second question" for m in prior)


def test_messages_wire_sanitizes_tool_call_and_result_names():
    history = [
        Message(role=Role.ASSISTANT, content="", tool_calls=[
            ToolCall(id="c1", name="shell.run", arguments={"command": "ls"}),
        ]),
        Message(role=Role.TOOL, tool_results=[
            ToolResult(tool_call_id="c1", name="shell.run", content="ok"),
        ]),
    ]
    wire = _messages_to_openai_wire(history)
    assistant = next(w for w in wire if w.get("tool_calls"))
    assert assistant["tool_calls"][0]["function"]["name"] == "shell_run"
    tool_msg = next(w for w in wire if w["role"] == "tool")
    assert tool_msg["tool_name"] == "shell_run"
