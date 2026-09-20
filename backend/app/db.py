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
  created_at TEXT NOT NULL,
  session_id TEXT
);
CREATE TABLE IF NOT EXISTS outputs (
  id TEXT PRIMARY KEY,
  stored_path TEXT NOT NULL UNIQUE,
  source_file_ids_json TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  output_name TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  messages_json TEXT NOT NULL,
  ui_messages_json TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
  session_id TEXT PRIMARY KEY,
  graph_json TEXT NOT NULL,
  stage TEXT NOT NULL,
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
        session_id: str | None = None,
    ):
        self.file_id = file_id
        self.original_name = original_name
        self.stored_path = stored_path
        self.file_type = file_type
        self.size_bytes = size_bytes
        self.sha256 = sha256
        self.inspection = inspection
        self.created_at = created_at
        self.session_id = session_id


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
        output_name: str | None = None,
    ):
        self.output_id = output_id
        self.stored_path = stored_path
        self.source_file_ids = source_file_ids
        self.plan = plan
        self.result = result
        self.status = status
        self.created_at = created_at
        self.output_name = output_name


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    _migrate_outputs(db_path)
    _migrate_sessions(db_path)
    _migrate_files(db_path)


def _migrate_files(db_path: Path) -> None:
    """Idempotent column add for `files.session_id` (legacy dbs pre-09-17).

    Rows written before this column existed keep NULL; they simply belong to no
    session and won't come back with a session's history.
    """
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("PRAGMA table_info(files)")
        cols = {row[1] for row in cur.fetchall()}
        if "session_id" not in cols:
            conn.execute("ALTER TABLE files ADD COLUMN session_id TEXT")
            conn.commit()


def _migrate_outputs(db_path: Path) -> None:
    """Idempotent column add for `outputs.output_name` (legacy dbs pre-09-17)."""
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("PRAGMA table_info(outputs)")
        cols = {row[1] for row in cur.fetchall()}
        if "output_name" not in cols:
            conn.execute("ALTER TABLE outputs ADD COLUMN output_name TEXT")
            conn.commit()


def _migrate_sessions(db_path: Path) -> None:
    """Idempotent column add for `sessions.ui_messages_json` (legacy dbs pre-09-17).

    Old rows have no UI transcript; `get_session_detail` falls back to deriving a
    text-only one from `messages_json`, so they still render instead of blanking.
    """
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in cur.fetchall()}
        if "ui_messages_json" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN ui_messages_json TEXT")
            conn.commit()


def insert_file(db_path: Path, record: FileRecord) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO files (id, original_name, stored_path, file_type, size_bytes, sha256, inspection_json, created_at, session_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.file_id,
                record.original_name,
                record.stored_path,
                record.file_type,
                record.size_bytes,
                record.sha256,
                json.dumps(record.inspection, ensure_ascii=False),
                record.created_at,
                record.session_id,
            ),
        )
        conn.commit()


def _row_to_file(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        file_id=row["id"],
        original_name=row["original_name"],
        stored_path=row["stored_path"],
        file_type=row["file_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        inspection=json.loads(row["inspection_json"]),
        created_at=row["created_at"],
        # Legacy rows (pre-migration) have no session_id column value at all.
        session_id=row["session_id"] if "session_id" in row.keys() else None,
    )


def get_file(db_path: Path, file_id: str) -> FileRecord | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,))
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_file(row)


def list_session_files(db_path: Path, session_id: str) -> list[FileRecord]:
    """Files uploaded within one session, oldest first.

    This is what makes an uploaded sheet survive a reload or a session switch:
    the bytes live in `uploads/`, this row is the link back to the conversation.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM files WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        rows = cur.fetchall()
    return [_row_to_file(row) for row in rows]


def _file_to_dto(rec: FileRecord) -> dict[str, Any]:
    """Shaped like FileUploadResponse, so the client reuses its upload mapper."""
    return {
        "file_id": rec.file_id,
        "filename": rec.original_name,
        "size_bytes": rec.size_bytes,
        "inspection": rec.inspection,
    }


def insert_output(db_path: Path, record: OutputRecord) -> None:
    """Write one output row, upserting on `id`.

    A node is re-run whenever the user revises upstream, and a side-effect node
    derives its output id from its node id — so the same id arrives again. Upsert
    keeps re-runs from piling up orphan rows (design.md §4 副作用幂等化).
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO outputs (id, stored_path, source_file_ids_json, plan_json, result_json, status, created_at, output_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET stored_path = excluded.stored_path, "
            "source_file_ids_json = excluded.source_file_ids_json, plan_json = excluded.plan_json, "
            "result_json = excluded.result_json, status = excluded.status, "
            "created_at = excluded.created_at, output_name = excluded.output_name",
            (
                record.output_id,
                record.stored_path,
                json.dumps(record.source_file_ids),
                json.dumps(record.plan, ensure_ascii=False),
                json.dumps(record.result, ensure_ascii=False),
                record.status,
                record.created_at,
                record.output_name,
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
    name = row["output_name"] if "output_name" in row.keys() else None
    return OutputRecord(
        output_id=row["id"],
        stored_path=row["stored_path"],
        source_file_ids=json.loads(row["source_file_ids_json"]),
        plan=json.loads(row["plan_json"]),
        result=json.loads(row["result_json"]),
        status=row["status"],
        created_at=row["created_at"],
        output_name=name,
    )


# ----- workflow graph persistence (the graph is the source of truth) -----


def save_workflow(db_path: Path, session_id: str, graph: dict[str, Any], stage: str) -> None:
    """Upsert one session's workflow graph + stage."""
    updated_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO workflows (session_id, graph_json, stage, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET graph_json = excluded.graph_json, "
            "stage = excluded.stage, updated_at = excluded.updated_at",
            (session_id, json.dumps(graph, ensure_ascii=False), stage, updated_at),
        )
        conn.commit()


def get_workflow(db_path: Path, session_id: str) -> dict[str, Any] | None:
    """Read back `{graph, stage}` for a session, or None when it has no graph."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT graph_json, stage FROM workflows WHERE session_id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    try:
        graph = json.loads(row["graph_json"])
    except (TypeError, ValueError):
        return None
    return {"graph": graph, "stage": row["stage"]}


# ----- session messages persistence (debug-only; not reloaded on startup) -----


def save_session_messages(
    db_path: Path,
    session_id: str,
    messages: list[Any],
    ui_messages: list[Any] | None = None,
) -> None:
    """Upsert the latest messages snapshot for a session.

    `messages` is the Anthropic-shaped context sent back to the model; `ui_messages`
    is the UI-shaped transcript (role/content/tool_calls/segments) the client
    renders. Both are written together so a reload shows the same interleaved
    timeline the user watched stream in.
    """
    payload = json.dumps(messages, ensure_ascii=False)
    ui_payload = json.dumps(ui_messages, ensure_ascii=False) if ui_messages is not None else None
    updated_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, messages_json, ui_messages_json, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET messages_json = excluded.messages_json, "
            "ui_messages_json = COALESCE(excluded.ui_messages_json, sessions.ui_messages_json), "
            "updated_at = excluded.updated_at",
            (session_id, payload, ui_payload, updated_at),
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


def _derive_ui_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Build a text-only UI transcript from the Anthropic-shaped history.

    Fallback for sessions written before `ui_messages_json` existed: they keep
    rendering their text instead of coming back empty. Tool rounds are invisible
    here — the anthropic-shaped history has no summary/status to rebuild them from.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            # A `user` turn holding only tool_result blocks is a synthetic tool
            # round-trip, not something the user typed — don't render it.
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                continue
            text = "".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content or "")
        if not text:
            continue
        out.append({
            "role": role if role in ("user", "assistant") else "assistant",
            "content": text,
            "tool_calls": [],
            "segments": [],
        })
    return out


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
            "SELECT session_id, messages_json, ui_messages_json, updated_at "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        # No messages yet — but a session that has an uploaded file is still a real
        # session (upload happens before the first message). Synthesize a detail so
        # its files come back instead of 404-ing the whole session away.
        files = list_session_files(db_path, session_id)
        if not files:
            return None
        return {
            "session_id": session_id,
            "title": "新会话",
            "updated_at": files[-1].created_at,
            "message_count": 0,
            "last_user_msg": "",
            "messages": [],
            "output_ids": [],
            "files": [_file_to_dto(f) for f in files],
            "has_more": False,
            "oldest_index": 0,
            "total_messages": 0,
        }
    try:
        messages = json.loads(row["messages_json"])
    except (TypeError, ValueError):
        messages = []

    # The client renders `ui_messages` (role/content/tool_calls/segments). The
    # Anthropic-shaped `messages` above stays the source for derived metadata.
    try:
        ui_messages = json.loads(row["ui_messages_json"]) if row["ui_messages_json"] else None
    except (TypeError, ValueError):
        ui_messages = None
    if not isinstance(ui_messages, list) or not ui_messages:
        ui_messages = _derive_ui_messages(messages)

    total_messages = len(ui_messages)
    if before_index is not None and before_index >= 0:
        ui_messages = ui_messages[:before_index]
        total_messages = len(ui_messages)
    if limit is not None and limit > 0 and len(ui_messages) > limit:
        page = ui_messages[-limit:]
        has_more = True
    else:
        page = ui_messages
        has_more = False

    oldest_index = max(0, len(ui_messages) - len(page))

    return {
        "session_id": row["session_id"],
        "title": _derive_title(messages),
        "updated_at": row["updated_at"],
        "message_count": total_messages,
        "last_user_msg": _derive_last_user_msg(messages),
        "messages": page,
        "output_ids": _extract_output_ids(messages),
        "files": [_file_to_dto(f) for f in list_session_files(db_path, session_id)],
        "has_more": has_more,
        "oldest_index": oldest_index,
        "total_messages": total_messages,
    }