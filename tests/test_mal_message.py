"""Tests for crabkey.mal.message — core message types."""

from crabkey.mal.message import (
    CompletionResponse,
    Message,
    Role,
    ToolCall,
    ToolResult,
    Usage,
)


def test_role_values():
    assert Role.SYSTEM.value == "system"
    assert Role.USER.value == "user"
    assert Role.ASSISTANT.value == "assistant"
    assert Role.TOOL.value == "tool"


def test_message_defaults():
    msg = Message(role=Role.USER, content="hello")
    assert msg.tool_calls == []
    assert msg.tool_results == []
    assert msg.name is None


def test_usage_total_tokens():
    u = Usage(input_tokens=10, output_tokens=5)
    assert u.total_tokens == 15


def test_usage_total_includes_both():
    u = Usage(input_tokens=100, output_tokens=50, cache_read_tokens=20)
    assert u.total_tokens == 150  # cache tokens are not double-counted


def test_tool_call_roundtrip():
    tc = ToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/x"})
    assert tc.id == "call_1"
    assert tc.arguments["path"] == "/tmp/x"


def test_tool_result_not_error_by_default():
    tr = ToolResult(tool_call_id="call_1", name="read_file", content="data")
    assert tr.is_error is False


def test_completion_response_fields():
    msg = Message(role=Role.ASSISTANT, content="done")
    usage = Usage(input_tokens=5, output_tokens=3)
    resp = CompletionResponse(message=msg, usage=usage, model="test-model", stop_reason="end_turn")
    assert resp.stop_reason == "end_turn"
    assert resp.usage.total_tokens == 8
