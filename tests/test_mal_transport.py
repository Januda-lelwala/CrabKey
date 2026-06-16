"""Tests for transport registry, ChatCompletionsTransport, and AnthropicMessagesTransport."""

import json
import types
import pytest

from crabkey.mal.transport import (
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
    get_transport,
    list_api_modes,
    register_transport,
)
from crabkey.mal.transports.chat_completions import ChatCompletionsTransport
from crabkey.mal.transports.anthropic_transport import AnthropicMessagesTransport


# ── Transport registry ────────────────────────────────────────────────────────

def test_both_transports_registered():
    modes = list_api_modes()
    assert "chat_completions" in modes
    assert "anthropic_messages" in modes


def test_get_transport_returns_instance():
    t = get_transport("chat_completions")
    assert isinstance(t, ChatCompletionsTransport)


def test_get_transport_unknown_raises():
    with pytest.raises(KeyError, match="no_such_mode"):
        get_transport("no_such_mode")


def test_register_custom_transport():
    class FakeTransport(ChatCompletionsTransport):
        @property
        def api_mode(self):
            return "fake_mode"

    register_transport("fake_mode", FakeTransport)
    assert "fake_mode" in list_api_modes()
    assert isinstance(get_transport("fake_mode"), FakeTransport)


# ── ChatCompletionsTransport ──────────────────────────────────────────────────

class TestChatCompletionsConvertMessages:
    def setup_method(self):
        self.t = ChatCompletionsTransport()

    def test_passthrough_clean_messages(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = self.t.convert_messages(msgs)
        assert result is msgs  # same object — no copy needed

    def test_strips_underscore_fields(self):
        msgs = [{"role": "user", "content": "hi", "_internal": "secret"}]
        result = self.t.convert_messages(msgs)
        assert "_internal" not in result[0]
        assert result[0]["content"] == "hi"

    def test_strips_tool_name_field(self):
        msgs = [{"role": "tool", "content": "ok", "tool_name": "read_file", "tool_call_id": "x"}]
        result = self.t.convert_messages(msgs)
        assert "tool_name" not in result[0]
        assert result[0]["tool_call_id"] == "x"

    def test_does_not_mutate_original(self):
        msgs = [{"role": "user", "content": "hi", "_flag": True}]
        self.t.convert_messages(msgs)
        assert "_flag" in msgs[0]


class TestChatCompletionsBuildKwargs:
    def setup_method(self):
        self.t = ChatCompletionsTransport()

    def test_basic_build(self):
        msgs = [{"role": "user", "content": "hello"}]
        kwargs = self.t.build_kwargs("gpt-4o", msgs, temperature=0.7, max_tokens=512)
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_tokens"] == 512

    def test_tools_included(self):
        msgs = [{"role": "user", "content": "x"}]
        tools = [{"type": "function", "function": {"name": "fn", "description": "d", "parameters": {}}}]
        kwargs = self.t.build_kwargs("gpt-4o", msgs, tools=tools)
        assert "tools" in kwargs

    def test_no_tools_omitted(self):
        msgs = [{"role": "user", "content": "x"}]
        kwargs = self.t.build_kwargs("gpt-4o", msgs)
        assert "tools" not in kwargs

    def test_omit_temperature_sentinel(self):
        from crabkey.mal.profile import OMIT_TEMPERATURE, ProviderProfile
        profile = ProviderProfile(name="test", fixed_temperature=OMIT_TEMPERATURE)
        msgs = [{"role": "user", "content": "x"}]
        kwargs = self.t.build_kwargs("model", msgs, provider_profile=profile, temperature=0.5)
        assert "temperature" not in kwargs

    def test_fixed_temperature_overrides_caller(self):
        from crabkey.mal.profile import ProviderProfile
        profile = ProviderProfile(name="test", fixed_temperature=0.0)
        msgs = [{"role": "user", "content": "x"}]
        kwargs = self.t.build_kwargs("model", msgs, provider_profile=profile, temperature=0.9)
        assert kwargs["temperature"] == 0.0


class TestChatCompletionsNormalizeResponse:
    def setup_method(self):
        self.t = ChatCompletionsTransport()

    def _make_response(self, content="hello", finish_reason="stop", tool_calls=None):
        msg = types.SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=None)
        choice = types.SimpleNamespace(message=msg, finish_reason=finish_reason)
        usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return types.SimpleNamespace(choices=[choice], usage=usage)

    def test_basic_text_response(self):
        raw = self._make_response("hello world")
        norm = self.t.normalize_response(raw)
        assert norm.content == "hello world"
        assert norm.tool_calls is None
        assert norm.finish_reason == "stop"

    def test_usage_extracted(self):
        raw = self._make_response()
        norm = self.t.normalize_response(raw)
        assert norm.usage.prompt_tokens == 10
        assert norm.usage.completion_tokens == 5

    def test_tool_calls_extracted(self):
        fn = types.SimpleNamespace(name="read_file", arguments='{"path": "/tmp/x"}')
        tc = types.SimpleNamespace(id="call_1", function=fn)
        raw = self._make_response(tool_calls=[tc], finish_reason="tool_calls")
        norm = self.t.normalize_response(raw)
        assert norm.finish_reason == "tool_calls"
        assert len(norm.tool_calls) == 1
        assert norm.tool_calls[0].name == "read_file"
        assert norm.tool_calls[0].id == "call_1"

    def test_validate_response_valid(self):
        raw = self._make_response()
        assert self.t.validate_response(raw) is True

    def test_validate_response_empty_choices(self):
        raw = types.SimpleNamespace(choices=[])
        assert self.t.validate_response(raw) is False


# ── AnthropicMessagesTransport ────────────────────────────────────────────────

class TestAnthropicConvertMessages:
    def setup_method(self):
        self.t = AnthropicMessagesTransport()

    def test_splits_system_message(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        system, converted = self.t.convert_messages(msgs)
        assert system == "You are helpful."
        assert len(converted) == 1
        assert converted[0]["role"] == "user"

    def test_no_system_returns_none(self):
        msgs = [{"role": "user", "content": "hi"}]
        system, converted = self.t.convert_messages(msgs)
        assert system is None
        assert len(converted) == 1

    def test_tool_result_converted(self):
        msgs = [{"role": "tool", "content": "result data", "tool_call_id": "tc_1"}]
        _, converted = self.t.convert_messages(msgs)
        assert converted[0]["role"] == "user"
        block = converted[0]["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tc_1"
        assert block["content"] == "result data"

    def test_assistant_with_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [{
                "id": "tc_1",
                "function": {"name": "read_file", "arguments": '{"path": "/x"}'},
            }],
        }]
        _, converted = self.t.convert_messages(msgs)
        content_blocks = converted[0]["content"]
        types_seen = {b["type"] for b in content_blocks}
        assert "text" in types_seen
        assert "tool_use" in types_seen


class TestAnthropicConvertTools:
    def setup_method(self):
        self.t = AnthropicMessagesTransport()

    def test_converts_to_input_schema(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }]
        result = self.t.convert_tools(tools)
        assert result[0]["name"] == "read_file"
        assert "input_schema" in result[0]
        assert "parameters" not in result[0]


class TestAnthropicBuildKwargs:
    def setup_method(self):
        self.t = AnthropicMessagesTransport()

    def test_system_extracted_to_top_level(self):
        msgs = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "hello"},
        ]
        kwargs = self.t.build_kwargs("claude-haiku-4-5-20251001", msgs)
        assert kwargs["system"] == "Be concise."
        assert all(m["role"] != "system" for m in kwargs["messages"])

    def test_max_tokens_default(self):
        msgs = [{"role": "user", "content": "hi"}]
        kwargs = self.t.build_kwargs("claude-sonnet-4-6", msgs)
        assert kwargs["max_tokens"] == 8192

    def test_max_tokens_from_param(self):
        msgs = [{"role": "user", "content": "hi"}]
        kwargs = self.t.build_kwargs("claude-sonnet-4-6", msgs, max_tokens=1024)
        assert kwargs["max_tokens"] == 1024


class TestAnthropicNormalizeResponse:
    def setup_method(self):
        self.t = AnthropicMessagesTransport()

    def _make_response(self, text="hello", stop_reason="end_turn", tool_blocks=None):
        blocks = [types.SimpleNamespace(type="text", text=text)]
        if tool_blocks:
            blocks.extend(tool_blocks)
        usage = types.SimpleNamespace(
            input_tokens=8, output_tokens=4,
            cache_read_input_tokens=0, cache_write_input_tokens=0,
        )
        return types.SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage)

    def test_text_response(self):
        raw = self._make_response("hello from claude")
        norm = self.t.normalize_response(raw)
        assert norm.content == "hello from claude"
        assert norm.tool_calls is None
        assert norm.finish_reason == "stop"

    def test_stop_reason_mapping(self):
        raw = self._make_response(stop_reason="max_tokens")
        norm = self.t.normalize_response(raw)
        assert norm.finish_reason == "length"

    def test_tool_use_blocks(self):
        tool_block = types.SimpleNamespace(
            type="tool_use",
            id="toolu_1",
            name="read_file",
            input={"path": "/tmp/x"},
        )
        raw = self._make_response(tool_blocks=[tool_block], stop_reason="tool_use")
        norm = self.t.normalize_response(raw)
        assert norm.finish_reason == "tool_calls"
        assert len(norm.tool_calls) == 1
        assert norm.tool_calls[0].name == "read_file"
        assert json.loads(norm.tool_calls[0].arguments) == {"path": "/tmp/x"}

    def test_usage_extracted(self):
        raw = self._make_response()
        norm = self.t.normalize_response(raw)
        assert norm.usage.prompt_tokens == 8
        assert norm.usage.completion_tokens == 4
