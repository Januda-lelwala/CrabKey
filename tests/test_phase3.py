"""Tests for Phase 3: hierarchical context, compression, commands, extensions."""

from pathlib import Path

import pytest

from crabkey.cognition.context_assembler import ContextAssembler, ContextBudget
from crabkey.cognition.context_files import load_context, resolve_imports
from crabkey.cognition.memory_manager import MemoryManager
from crabkey.cli.commands import expand, load_custom_commands
from crabkey.cli.extensions import load_extensions
from crabkey.mal.message import Message, Role


# --------------------------------------------------------------------------- #
# Hierarchical context + @imports
# --------------------------------------------------------------------------- #

def test_resolve_imports_inlines_referenced_file(tmp_path):
    (tmp_path / "shared.md").write_text("SHARED CONTENT")
    text = "Top\n@shared.md\nEnd"
    out = resolve_imports(text, tmp_path)
    assert "SHARED CONTENT" in out
    assert "@shared.md" not in out


def test_resolve_imports_leaves_missing_token(tmp_path):
    out = resolve_imports("see @nope.md", tmp_path)
    assert "@nope.md" in out  # unresolved tokens are preserved


def test_resolve_imports_handles_cycles(tmp_path):
    (tmp_path / "a.md").write_text("A @b.md")
    (tmp_path / "b.md").write_text("B @a.md")
    out = resolve_imports("@a.md", tmp_path)
    # Should terminate and include both, without infinite recursion.
    assert "A" in out and "B" in out


def test_load_context_merges_global_then_project(tmp_path):
    g = tmp_path / "global.md"
    p = tmp_path / "project.md"
    g.write_text("GLOBAL")
    p.write_text("PROJECT")
    merged = load_context([g, p])
    assert merged.index("GLOBAL") < merged.index("PROJECT")


def test_load_context_returns_none_when_empty(tmp_path):
    assert load_context([tmp_path / "missing.md"]) is None


def test_memory_manager_uses_hierarchy(tmp_path):
    g = tmp_path / "g.md"
    p = tmp_path / "p.md"
    ext = tmp_path / "ext.md"
    g.write_text("G")
    ext.write_text("E")
    p.write_text("P")
    mm = MemoryManager(context_file=p, global_context_file=g, extra_context_files=[ext])
    doc = mm.load_context_file()
    assert doc.index("G") < doc.index("E") < doc.index("P")


# --------------------------------------------------------------------------- #
# Context compression
# --------------------------------------------------------------------------- #

async def test_assembler_summarizes_dropped_history():
    summarized: list[list[Message]] = []

    async def fake_summarizer(msgs):
        summarized.append(msgs)
        return "SUMMARY OF OLD STUFF"

    # Tiny budget so most history is dropped.
    budget = ContextBudget(max_tokens=60, system_reserve=0, memory_reserve=0, history_reserve=0)
    assembler = ContextAssembler(MemoryManager(), budget=budget, summarizer=fake_summarizer)

    history = [Message(role=Role.USER, content="x" * 200) for _ in range(5)]
    messages = await assembler.build(history, base_system="sys")

    assert summarized, "summarizer should have been called for dropped messages"
    system_msg = messages[0]
    assert system_msg.role == Role.SYSTEM
    assert "SUMMARY OF OLD STUFF" in system_msg.content


async def test_assembler_no_summarizer_just_truncates():
    budget = ContextBudget(max_tokens=60, system_reserve=0, memory_reserve=0, history_reserve=0)
    assembler = ContextAssembler(MemoryManager(), budget=budget)
    history = [Message(role=Role.USER, content="x" * 200) for _ in range(5)]
    messages = await assembler.build(history, base_system="sys")
    # No summary block when no summarizer.
    assert "conversation_summary" not in (messages[0].content or "")


# --------------------------------------------------------------------------- #
# Custom commands
# --------------------------------------------------------------------------- #

def test_expand_substitutes_or_appends():
    assert expand("Review: {{args}}", "the diff") == "Review: the diff"
    assert expand("Summarize", "extra") == "Summarize\n\nextra"
    assert expand("No args", "") == "No args"


def test_load_custom_commands(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    (d / "review.toml").write_text('description = "Review"\nprompt = "Review this: {{args}}"\n')
    (d / "bad.toml").write_text('description = "no prompt here"\n')  # skipped: no prompt
    cmds = load_custom_commands([d])
    assert "review" in cmds
    assert "bad" not in cmds
    assert cmds["review"].description == "Review"


def test_load_custom_commands_later_dir_overrides(tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir(); d2.mkdir()
    (d1 / "x.toml").write_text('prompt = "from A"\n')
    (d2 / "x.toml").write_text('prompt = "from B"\n')
    cmds = load_custom_commands([d1, d2])
    assert cmds["x"].prompt == "from B"


# --------------------------------------------------------------------------- #
# Extensions
# --------------------------------------------------------------------------- #

def test_load_extensions_discovers_bundle(tmp_path):
    ext = tmp_path / ".crabkey" / "extensions" / "pg"
    (ext / "commands").mkdir(parents=True)
    (ext / "context.md").write_text("postgres context")
    (ext / "commands" / "query.toml").write_text('prompt = "run {{args}}"\n')
    (ext / "crabkey-extension.toml").write_text(
        'name = "postgres"\n'
        '[[mcp_servers]]\n'
        'name = "pg"\n'
        'command = "npx"\n'
        'args = ["-y", "server-postgres"]\n'
    )
    loaded = load_extensions(tmp_path)
    assert loaded.names == ["postgres"]
    assert len(loaded.mcp_servers) == 1
    assert loaded.mcp_servers[0]["command"] == "npx"
    assert loaded.context_files and loaded.context_files[0].name == "context.md"
    assert loaded.command_dirs and loaded.command_dirs[0].name == "commands"


def test_load_extensions_empty_when_no_dir(tmp_path):
    loaded = load_extensions(tmp_path)
    assert loaded.names == []
    assert loaded.mcp_servers == []
