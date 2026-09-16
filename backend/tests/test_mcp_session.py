"""Tests for Session / SessionStore lifecycle."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from backend.app.mcp.session import SESSION_TTL_SECONDS, Session, SessionStore


def test_session_initial_state(tmp_path: Path) -> None:
    s = Session("abc", tmp_path)
    assert s.session_id == "abc"
    assert s.tables == {}
    assert s.messages == []
    assert s.tool_calls_log == []
    assert s.audit_events == []
    assert s.output_id is None
    assert s.is_expired() is False
    assert s.has_file("any") is False


def test_session_touch_updates_timestamp() -> None:
    s = Session("abc", Path("/tmp"))
    original = s.updated_at
    time.sleep(0.01)
    s.touch()
    assert s.updated_at > original


def test_session_is_expired_after_ttl() -> None:
    s = Session("abc", Path("/tmp"))
    s.updated_at -= SESSION_TTL_SECONDS + 10
    assert s.is_expired() is True


def test_session_can_hold_tables() -> None:
    s = Session("abc", Path("/tmp"))
    df = pd.DataFrame({"a": [1, 2]})
    s.tables["ref"] = df
    assert s.tables["ref"].equals(df)


def test_session_lock_serializes(tmp_path: Path) -> None:
    s = Session("abc", tmp_path)
    assert s.lock.acquire(blocking=False)
    s.lock.release()


def test_store_get_or_create_creates(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")
    s = store.get_or_create("sid")
    assert s.session_id == "sid"
    assert store.get_or_create("sid") is s


def test_store_get_or_create_separates_ids(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")
    s1 = store.get_or_create("a")
    s2 = store.get_or_create("b")
    assert s1 is not s2


def test_store_get_returns_none_for_unknown(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")
    assert store.get("missing") is None


def test_store_get_returns_expired_none(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")
    s = store.get_or_create("sid")
    s.updated_at -= SESSION_TTL_SECONDS + 10
    assert store.get("sid") is None


def test_store_get_or_create_evicts_expired(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")
    s_old = store.get_or_create("sid")
    s_old.updated_at -= SESSION_TTL_SECONDS + 10
    s_new = store.get_or_create("sid")
    assert s_new is not s_old


def test_store_drop(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")
    store.get_or_create("sid")
    store.drop("sid")
    assert store.get("sid") is None


def test_store_cleanup_expired(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")
    store.get_or_create("a")
    s_b = store.get_or_create("b")
    s_b.updated_at -= SESSION_TTL_SECONDS + 10
    removed = store.cleanup_expired()
    assert removed == 1
    assert store.get("a") is not None
    assert store.get("b") is None


def test_get_session_store_singleton(tmp_path: Path, monkeypatch) -> None:
    from backend.app import mcp
    from backend.app.config import get_settings

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    mcp.session.reset_session_store()
    s1 = mcp.session.get_session_store()
    s2 = mcp.session.get_session_store()
    assert s1 is s2


def test_persist_messages_writes_to_sqlite(tmp_path: Path) -> None:
    """Per plan §1.2.3 (simplified): messages are persisted to SQLite for debug, not reloaded."""
    from backend.app.db import get_session_messages, init_db

    db_path = tmp_path / "metadata.db"
    init_db(db_path)
    store = SessionStore(tmp_path / "out", db_path=db_path)
    session = store.get_or_create("sid")
    session.messages.append({"role": "user", "content": "hi"})
    store.persist_messages(session)

    loaded = get_session_messages(db_path, "sid")
    assert loaded == [{"role": "user", "content": "hi"}]

    session.messages.append({"role": "assistant", "content": "reply"})
    store.persist_messages(session)
    loaded = get_session_messages(db_path, "sid")
    assert loaded[-1] == {"role": "assistant", "content": "reply"}


def test_persist_messages_no_op_without_db_path(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "out")  # no db_path
    session = store.get_or_create("sid")
    session.messages.append({"role": "user", "content": "hi"})
    store.persist_messages(session)  # must not raise