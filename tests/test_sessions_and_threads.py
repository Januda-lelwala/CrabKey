"""Tests for session/thread management and ConversationContext."""

import pytest
from pathlib import Path

from crabkey.persistence.db import Db
from crabkey.orchestration.session_manager import Session, SessionManager
from crabkey.orchestration.thread_manager import Thread, ThreadManager
from crabkey.cli.repl import ConversationContext
from crabkey.mal.message import Role


@pytest.fixture
async def db(tmp_path):
    d = Db(tmp_path / "test.db")
    await d.initialize()
    return d


@pytest.fixture
async def session_mgr(db):
    return SessionManager(db)


@pytest.fixture
async def thread_mgr(db):
    return ThreadManager(db)


# ── SessionManager ────────────────────────────────────────────────────────────

async def test_new_session_becomes_active(session_mgr):
    sess = await session_mgr.new("my-session")
    assert session_mgr.active is sess
    assert sess.name == "my-session"


async def test_new_session_auto_names(session_mgr):
    sess = await session_mgr.new()
    assert sess.name.startswith("session-")


async def test_session_persists_to_db(session_mgr, db):
    sess = await session_mgr.new("persisted")
    record = await db.get_session(sess.id)
    assert record is not None
    assert record.name == "persisted"


async def test_switch_session_by_name(session_mgr):
    s1 = await session_mgr.new("alpha")
    s2 = await session_mgr.new("beta")      # now active
    assert session_mgr.active is s2

    back = await session_mgr.switch("alpha")
    assert back is s1
    assert session_mgr.active is s1


async def test_switch_session_by_id_prefix(session_mgr):
    sess = await session_mgr.new("gamma")
    prefix = sess.id[:6]
    result = await session_mgr.switch(prefix)
    assert result.id == sess.id


async def test_switch_unknown_session_raises(session_mgr):
    with pytest.raises(KeyError, match="not found"):
        await session_mgr.switch("no-such-session")


async def test_list_sessions(session_mgr):
    await session_mgr.new("one")
    await session_mgr.new("two")
    records = await session_mgr.list_all()
    names = {r.name for r in records}
    assert {"one", "two"}.issubset(names)


async def test_append_message_to_session(session_mgr):
    sess = await session_mgr.new("chat")
    await session_mgr.append_message("user", "hello")
    await session_mgr.append_message("assistant", "hi there")
    assert len(sess.messages) == 2
    assert sess.messages[0].role == Role.USER
    assert sess.messages[1].role == Role.ASSISTANT


async def test_session_messages_reload_from_db(db):
    mgr1 = SessionManager(db)
    sess = await mgr1.new("reload-test")
    await mgr1.append_message("user", "remember this")

    # New manager — loads from DB
    mgr2 = SessionManager(db)
    loaded = await mgr2.switch(sess.id)
    assert len(loaded.messages) == 1
    assert loaded.messages[0].content == "remember this"


# ── ThreadManager ─────────────────────────────────────────────────────────────

async def test_new_thread_becomes_active(session_mgr, thread_mgr):
    sess = await session_mgr.new("session-a")
    thr = await thread_mgr.new(session_id=sess.id, name="my-thread")
    assert thread_mgr.active is thr
    assert thr.name == "my-thread"
    assert thr.session_id == sess.id


async def test_thread_records_fork_point(session_mgr, thread_mgr):
    sess = await session_mgr.new("session-b")
    await session_mgr.append_message("user", "msg1")
    await session_mgr.append_message("assistant", "msg2")

    thr = await thread_mgr.new(session_id=sess.id, forked_at=len(sess.messages))
    assert thr.forked_at == 2


async def test_exit_thread_clears_active(session_mgr, thread_mgr):
    sess = await session_mgr.new("session-c")
    await thread_mgr.new(session_id=sess.id)
    assert thread_mgr.active is not None

    thread_mgr.exit_thread()
    assert thread_mgr.active is None


async def test_thread_history_is_isolated(session_mgr, thread_mgr):
    sess = await session_mgr.new("session-d")
    await session_mgr.append_message("user", "session message")

    thr = await thread_mgr.new(session_id=sess.id, forked_at=len(sess.messages))
    await thread_mgr.append_message("user", "thread only")

    # Thread history has only the thread-local message
    assert len(thr.history) == 1
    assert thr.history[0].content == "thread only"

    # Session messages unchanged
    assert len(sess.messages) == 1
    assert sess.messages[0].content == "session message"


async def test_thread_persists_and_reloads(session_mgr, thread_mgr, db):
    sess = await session_mgr.new("session-e")
    await session_mgr.append_message("user", "base")
    thr = await thread_mgr.new(session_id=sess.id, name="my-thread", forked_at=1)
    await thread_mgr.append_message("user", "thread msg")

    record = await db.get_thread(thr.id)
    assert record.forked_at == 1
    assert record.name == "my-thread"

    rows = await db.get_messages(thr.id)
    assert len(rows) == 1
    assert rows[0].content == "thread msg"
    assert rows[0].owner_type == "thread"


# ── ConversationContext ───────────────────────────────────────────────────────

async def test_context_in_session_returns_all_messages(session_mgr, thread_mgr, db):
    sess = await session_mgr.new("ctx-session")
    await session_mgr.append_message("user", "hello")
    await session_mgr.append_message("assistant", "hi")

    ctx = ConversationContext(session_mgr, thread_mgr, db)
    messages = ctx.get_context_messages()
    assert len(messages) == 2


async def test_context_in_thread_combines_session_and_thread(session_mgr, thread_mgr, db):
    sess = await session_mgr.new("ctx-fork-session")
    await session_mgr.append_message("user", "session msg 1")
    await session_mgr.append_message("assistant", "session msg 2")

    # Fork thread here — session has 2 messages
    thr = await thread_mgr.new(session_id=sess.id, forked_at=2)
    await thread_mgr.append_message("user", "thread msg")

    ctx = ConversationContext(session_mgr, thread_mgr, db)
    messages = ctx.get_context_messages()
    # Should be: 2 session messages + 1 thread message = 3
    assert len(messages) == 3
    assert messages[0].content == "session msg 1"
    assert messages[1].content == "session msg 2"
    assert messages[2].content == "thread msg"


async def test_context_thread_only_sees_session_up_to_fork(session_mgr, thread_mgr, db):
    sess = await session_mgr.new("ctx-fork-isolation")
    await session_mgr.append_message("user", "msg before fork")

    thr = await thread_mgr.new(session_id=sess.id, forked_at=1)

    # Add more messages to the session AFTER fork (simulates switching back)
    sess.messages.append(__import__("crabkey.mal.message", fromlist=["Message"]).Message(
        role=Role.USER, content="msg after fork (session)"
    ))

    ctx = ConversationContext(session_mgr, thread_mgr, db)
    messages = ctx.get_context_messages()
    # Thread should only see the 1 message at fork point, not the later session message
    contents = [m.content for m in messages]
    assert "msg before fork" in contents
    assert "msg after fork (session)" not in contents


async def test_context_after_exit_thread_returns_session_only(session_mgr, thread_mgr, db):
    sess = await session_mgr.new("exit-test")
    await session_mgr.append_message("user", "session only")

    thr = await thread_mgr.new(session_id=sess.id, forked_at=1)
    await thread_mgr.append_message("user", "thread only")

    thread_mgr.exit_thread()

    ctx = ConversationContext(session_mgr, thread_mgr, db)
    messages = ctx.get_context_messages()
    contents = [m.content for m in messages]
    assert "session only" in contents
    assert "thread only" not in contents


async def test_prompt_label_shows_session_and_thread(session_mgr, thread_mgr, db):
    sess = await session_mgr.new("my-session")
    ctx = ConversationContext(session_mgr, thread_mgr, db)
    label = ctx.prompt_label()
    assert "my-session" in label
    assert "thread" not in label.lower()

    await thread_mgr.new(session_id=sess.id, name="my-thread", forked_at=0)
    label = ctx.prompt_label()
    assert "my-session" in label
    assert "my-thread" in label


# ── DB layer: sessions and messages ──────────────────────────────────────────

async def test_db_messages_owner_type_recorded(db):
    await db.create_session("s1", "test-session")
    await db.append_message("s1", "session", "user", "hello")
    rows = await db.get_messages("s1")
    assert rows[0].owner_type == "session"
    assert rows[0].owner_id == "s1"


async def test_db_thread_messages_separate_from_session(db):
    await db.create_session("s2", "sep-session")
    await db.create_thread("t1", "s2", "sep-thread", forked_at=0)
    await db.append_message("s2", "session", "user", "session msg")
    await db.append_message("t1", "thread", "user", "thread msg")

    s_rows = await db.get_messages("s2")
    t_rows = await db.get_messages("t1")
    assert len(s_rows) == 1 and s_rows[0].content == "session msg"
    assert len(t_rows) == 1 and t_rows[0].content == "thread msg"


async def test_db_count_messages(db):
    await db.create_session("s3", "count-session")
    await db.append_message("s3", "session", "user", "a")
    await db.append_message("s3", "session", "assistant", "b")
    assert await db.count_messages("s3") == 2


async def test_db_list_threads_for_session(db):
    await db.create_session("s4", "list-threads-session")
    await db.create_thread("t2", "s4", "thread-one", forked_at=0)
    await db.create_thread("t3", "s4", "thread-two", forked_at=1)
    records = await db.list_threads_for_session("s4")
    names = {r.name for r in records}
    assert names == {"thread-one", "thread-two"}
