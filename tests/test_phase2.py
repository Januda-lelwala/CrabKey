"""Tests for Phase 2: search tools, save_memory, web search, and streaming."""

from types import SimpleNamespace

import pytest

from crabkey.mal.message import CompletionResponse, Message, Role, Usage
from crabkey.mal.plugin_provider import _accumulate_openai_stream
from crabkey.mal.provider import ModelConfig
from crabkey.orchestration.loop_engine import LoopConfig, LoopEngine
from crabkey.safety.permission_broker import Permission, PermissionBroker, PermissionLevel
from crabkey.tools.base import ToolContext, ToolRegistry
from crabkey.tools.memory_tool import SaveMemoryTool
from crabkey.tools.search_tool import GlobTool, GrepTool
from crabkey.tools.web_tool import WebSearchTool


# --------------------------------------------------------------------------- #
# Search tools
# --------------------------------------------------------------------------- #

@pytest.fixture
def tree(tmp_path):
    (tmp_path / "a.py").write_text("import os\ndef foo():\n    return TARGET\n")
    (tmp_path / "b.txt").write_text("nothing here\nTARGET also here\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("x = 1  # target lowercase\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.py").write_text("TARGET should be skipped\n")
    return tmp_path


async def test_grep_python_fallback_finds_matches(tree):
    tool = GrepTool()
    ctx = ToolContext(working_dir=str(tree))
    out = tool._run_python(tree, "TARGET", "*", ignore_case=False, max_results=100)
    joined = "\n".join(out)
    assert "a.py:3" in joined
    assert "b.txt:2" in joined
    assert "node_modules" not in joined  # skipped dir
    assert "c.py" not in joined           # lowercase 'target' not matched (case-sensitive)


async def test_grep_glob_filter_and_ignore_case(tree):
    tool = GrepTool()
    out = tool._run_python(tree, "target", "*.py", ignore_case=True, max_results=100)
    joined = "\n".join(out)
    assert "a.py" in joined and "c.py" in joined
    assert "b.txt" not in joined  # filtered out by *.py glob


async def test_glob_lists_python_files(tree):
    tool = GlobTool()
    ctx = ToolContext(working_dir=str(tree))
    out = await tool.run({"pattern": "**/*.py"}, ctx)
    assert "a.py" in out and "c.py" in out
    assert "node_modules" not in out


# --------------------------------------------------------------------------- #
# save_memory tool
# --------------------------------------------------------------------------- #

async def test_save_memory_creates_and_dedupes(tmp_path):
    ctx_file = tmp_path / "CONTEXT.md"
    tool = SaveMemoryTool(context_file=ctx_file)
    ctx = ToolContext(working_dir=str(tmp_path))

    r1 = await tool.run({"fact": "Uses pytest for tests"}, ctx)
    assert "Remembered" in r1
    content = ctx_file.read_text()
    assert "## CrabKey Memory" in content
    assert "- Uses pytest for tests" in content

    r2 = await tool.run({"fact": "Prefers minimal diffs"}, ctx)
    assert "- Prefers minimal diffs" in ctx_file.read_text()
    # Both facts under the single heading.
    assert ctx_file.read_text().count("## CrabKey Memory") == 1

    r3 = await tool.run({"fact": "Uses pytest for tests"}, ctx)
    assert "Already remembered" in r3


async def test_save_memory_preserves_existing_content(tmp_path):
    ctx_file = tmp_path / "CONTEXT.md"
    ctx_file.write_text("# Project\n\nSome existing docs.\n")
    tool = SaveMemoryTool(context_file=ctx_file)
    await tool.run({"fact": "Remember this"}, ToolContext(working_dir=str(tmp_path)))
    content = ctx_file.read_text()
    assert "Some existing docs." in content
    assert "- Remember this" in content


# --------------------------------------------------------------------------- #
# Web search
# --------------------------------------------------------------------------- #

async def test_web_search_no_backend_raises(monkeypatch):
    for var in ("TAVILY_API_KEY", "BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    tool = WebSearchTool()
    with pytest.raises(RuntimeError, match="No web search backend"):
        await tool.run({"query": "hello"}, ToolContext(working_dir="."))


def test_web_search_format():
    out = WebSearchTool._format([
        {"title": "T", "url": "http://x", "snippet": "S"},
    ])
    assert "T" in out and "http://x" in out and "S" in out
    assert WebSearchTool._format([]) == "No results."


# --------------------------------------------------------------------------- #
# Streaming accumulator
# --------------------------------------------------------------------------- #

def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tc(index, id=None, name=None, arguments=None):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


async def _gen(chunks):
    for c in chunks:
        yield c


async def test_accumulate_text_stream():
    seen: list[str] = []
    chunks = [
        _chunk(content="Hel"),
        _chunk(content="lo"),
        _chunk(finish_reason="stop", usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2)),
    ]
    resp = await _accumulate_openai_stream(_gen(chunks), "m", seen.append)
    assert resp.message.content == "Hello"
    assert seen == ["Hel", "lo"]
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 3 and resp.usage.output_tokens == 2


async def test_accumulate_tool_call_stream():
    # Tool call arrives fragmented across chunks (name first, then args in pieces).
    chunks = [
        _chunk(tool_calls=[_tc(0, id="call_1", name="file.read")]),
        _chunk(tool_calls=[_tc(0, arguments='{"path":')]),
        _chunk(tool_calls=[_tc(0, arguments='"a.py"}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    resp = await _accumulate_openai_stream(_gen(chunks), "m", None)
    assert resp.stop_reason == "tool_use"
    assert len(resp.message.tool_calls) == 1
    tc = resp.message.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.name == "file.read"
    assert tc.arguments == {"path": "a.py"}


# --------------------------------------------------------------------------- #
# LoopEngine streaming integration
# --------------------------------------------------------------------------- #

class _StreamingProvider:
    name = "fake"

    async def complete(self, messages, config, tools=None):  # pragma: no cover - not used
        raise AssertionError("streaming path should call stream_complete")

    async def stream_complete(self, messages, config, tools=None, *, on_text=None, **kw):
        for piece in ("Wor", "king"):
            if on_text:
                on_text(piece)
        msg = Message(role=Role.ASSISTANT, content="Working")
        return CompletionResponse(message=msg, usage=Usage(), model="fake", stop_reason="end_turn")


class _FakeAssembler:
    async def build(self, history, base_system=None, **kwargs):
        return list(history)


class _FakeDb:
    async def log_cost(self, *a, **k):
        return None


async def test_loop_emits_text_deltas_when_streaming():
    events: list[tuple[str, str]] = []
    broker = PermissionBroker()
    broker.add_rule(Permission(tool="*", level=PermissionLevel.ALLOW))
    loop = LoopEngine(
        provider=_StreamingProvider(),
        tools=ToolRegistry(),
        assembler=_FakeAssembler(),
        db=_FakeDb(),
        broker=broker,
        config=LoopConfig(max_iterations=2, stream=True),
    )
    await loop.run(
        goal="g", thread_id="t", model_config=ModelConfig(model="fake"), working_dir="/tmp",
        on_event=lambda e: events.append((e.kind, e.data)),
    )
    deltas = [d for k, d in events if k == "text_delta"]
    assert deltas == ["Wor", "king"]
    # No full "text" event should be emitted while streaming.
    assert not any(k == "text" for k, _ in events)
