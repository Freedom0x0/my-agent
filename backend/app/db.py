"""SQLite metadata helpers."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL UNIQUE,
  file_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  inspection_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outputs (
  id TEXT PRIMARY KEY,
  stored_path TEXT NOT NULL UNIQUE,
  source_file_ids_json TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  messages_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


class FileRecord:
    def __init__(
        self,
        file_id: str,
        original_name: str,
        stored_path: str,
        file_type: str,
        size_bytes: int,
        sha256: str,
        inspection: dict[str, Any],
        created_at: str,
    ):
        self.file_id = file_id
        self.original_name = original_name
        self.stored_path = stored_path
        self.file_type = file_type
        self.size_bytes = size_bytes
        self.sha256 = sha256
        self.inspection = inspection
        self.created_at = created_at


class OutputRecord:
    def __init__(
        self,
        output_id: str,
        stored_path: str,
        source_file_ids: list[str],
        plan: dict[str, Any],
        result: dict[str, Any],
        status: str,
        created_at: str,
    ):
        self.output_id = output_id
        self.stored_path = stored_path
        self.source_file_ids = source_file_ids
        self.plan = plan
        self.result = result
        self.status = status
        self.created_at = created_at


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def insert_file(db_path: Path, record: FileRecord) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO files (id, original_name, stored_path, file_type, size_bytes, sha256, inspection_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.file_id,
                record.original_name,
                record.stored_path,
                record.file_type,
                record.size_bytes,
                record.sha256,
                json.dumps(record.inspection, ensure_ascii=False),
                record.created_at,
            ),
        )
        conn.commit()


def get_file(db_path: Path, file_id: str) -> FileRecord | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,))
        row = cur.fetchone()
    if not row:
        return None
    return FileRecord(
        file_id=row["id"],
        original_name=row["original_name"],
        stored_path=row["stored_path"],
        file_type=row["file_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        inspection=json.loads(row["inspection_json"]),
        created_at=row["created_at"],
    )


def insert_output(db_path: Path, record: OutputRecord) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO outputs (id, stored_path, source_file_ids_json, plan_json, result_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.output_id,
                record.stored_path,
                json.dumps(record.source_file_ids),
                json.dumps(record.plan, ensure_ascii=False),
                json.dumps(record.result, ensure_ascii=False),
                record.status,
                record.created_at,
            ),
        )
        conn.commit()


def get_output(db_path: Path, output_id: str) -> OutputRecord | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM outputs WHERE id = ?", (output_id,))
        row = cur.fetchone()
    if not row:
        return None
    return OutputRecord(
        output_id=row["id"],
        stored_path=row["stored_path"],
        source_file_ids=json.loads(row["source_file_ids_json"]),
        plan=json.loads(row["plan_json"]),
        result=json.loads(row["result_json"]),
        status=row["status"],
        created_at=row["created_at"],
    )


# ----- session messages persistence (debug-only; not reloaded on startup) -----


def save_session_messages(db_path: Path, session_id: str, messages: list[Any]) -> None:
    """Upsert the latest messages snapshot for a session. Debug-only — not read on startup."""
    payload = json.dumps(messages, ensure_ascii=False)
    updated_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, messages_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET messages_json = excluded.messages_json, "
            "updated_at = excluded.updated_at",
            (session_id, payload, updated_at),
        )
        conn.commit()


def get_session_messages(db_path: Path, session_id: str) -> list[Any] | None:
    """Read back a session's messages if any. Returns None when the row is missing."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT messages_json FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
    if not row:
        return None
    return json.loads(row["messages_json"])


# ----- session listing for sidebar -----


def _derive_title(messages: list[Any]) -> str:
    """Take the first user message, strip to 30 chars; fall back to a placeholder."""
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, list):
            text = "".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content or "")
        text = text.strip().replace("\n", " ")
        if text:
            return text[:30] + ("…" if len(text) > 30 else "")
    return "新会话"


def _derive_last_user_msg(messages: list[Any]) -> str:
    for m in reversed(messages):
        if not isinstance(m, dict):
            continue
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, list):
            text = "".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content or "")
        text = text.strip().replace("\n", " ")
        if text:
            return text[:40] + ("…" if len(text) > 40 else "")
    return ""


def _extract_output_ids(messages: list[Any]) -> list[str]:
    """Grep output_id out of any persisted tool_use/tool_result blocks (best-effort)."""
    ids: list[str] = []
    seen: set[str] = set()
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                oid = block.get("output_id")
                if isinstance(oid, str) and oid and oid not in seen:
                    ids.append(oid)
                    seen.add(oid)
    return ids


def list_sessions(db_path: Path) -> list[dict[str, Any]]:
    """Return one summary row per session, newest first."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT session_id, messages_json, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    summaries: list[dict[str, Any]] = []
    for row in rows:
        try:
            messages = json.loads(row["messages_json"])
        except (TypeError, ValueError):
            messages = []
        summaries.append(
            {
                "session_id": row["session_id"],
                "title": _derive_title(messages),
                "updated_at": row["updated_at"],
                "message_count": len(messages),
                "last_user_msg": _derive_last_user_msg(messages),
            }
        )
    return summaries


def get_session_detail(
    db_path: Path,
    session_id: str,
    *,
    limit: int | None = None,
    before_index: int | None = None,
) -> dict[str, Any] | None:
    """Return one session's detail (messages + extracted metadata) or None.

    Lazy-load contract:
      * `limit`        — return at most N messages from the tail end of the full history.
      * `before_index` — slice the history to messages with positional index < before_index.
      * The response always carries `total_messages`, `oldest_index` (the index of the
        first message in the returned page, or 0 if empty), and `has_more` (whether
        older messages exist before the page).
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT session_id, messages_json, updated_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    try:
        messages = json.loads(row["messages_json"])
    except (TypeError, ValueError):
        messages = []

    total_messages = len(messages)
    if before_index is not None and before_index >= 0:
        messages = messages[:before_index]
        total_messages = len(messages)
    if limit is not None and limit > 0 and len(messages) > limit:
        page = messages[-limit:]
        has_more = True
    else:
        page = messages
        has_more = False

    oldest_index = max(0, len(messages) - len(page))

    return {
        "session_id": row["session_id"],
        "title": _derive_title(messages),
        "updated_at": row["updated_at"],
        "message_count": total_messages,
        "last_user_msg": _derive_last_user_msg(messages),
        "messages": page,
        "output_ids": _extract_output_ids(messages),
        "has_more": has_more,
        "oldest_index": oldest_index,
        "total_messages": total_messages,
    }