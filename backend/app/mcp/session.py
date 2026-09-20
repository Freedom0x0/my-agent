"""In-memory session state and TTL-based session store."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    pass

SESSION_TTL_SECONDS = 30 * 60  # ponytail: global lock, single-process; per-session store if we ever shard.


class Session:
    """One conversation's mutable state.

    - `tables`: current DataFrames keyed by SheetRef (`<file_id>::<sheet>`). NOT serialized.
    - `graph` + `stage`: the workflow graph and where the session sits in the state
      machine. Cached here, persisted to SQLite (the graph is the truth).
    - `messages`: Anthropic Messages API history.
    - `tool_calls_log`: list of `{tool, status, summary}` for the UI.
    - `audit_events`: list of AuditEvent produced by handlers.
    - `lock`: serializes concurrent requests for the same session.
    """

    def __init__(self, session_id: str, output_dir: Path):
        self.session_id = session_id
        self.files: dict[str, dict[str, Any]] = {}  # file_id -> {path, sha256, original_name}
        self.tables: dict[str, pd.DataFrame] = {}
        # The workflow graph is the truth and lives in SQLite; this is a cache of
        # it (`None` until the model proposes one). `stage` is the state machine.
        self.graph: dict[str, Any] | None = None
        self.stage: str = "drafting"
        self.messages: list[dict[str, Any]] = []
        # UI-shaped transcript (role/content/tool_calls/segments) rendered by the
        # client. Persisted to sessions.ui_messages_json so a reload rebuilds the
        # same interleaved timeline the user saw while streaming.
        self.ui_messages: list[dict[str, Any]] = []
        self.tool_calls_log: list[dict[str, Any]] = []
        self.audit_events: list[Any] = []
        self.output_id: str | None = None
        self.output_path: str | None = None
        self.output_dir = output_dir
        # Set per turn from the request context so tool logs can be traced back to
        # the request that triggered them.
        self.request_id: str | None = None
        self.lock = threading.Lock()
        self.created_at = time.time()
        self.updated_at = self.created_at

    def touch(self) -> None:
        self.updated_at = time.time()

    def is_expired(self) -> bool:
        return (time.time() - self.updated_at) > SESSION_TTL_SECONDS

    def has_file(self, file_id: str) -> bool:
        return file_id in self.files


class SessionStore:
    """Process-local session registry with TTL expiry.

    `db_path` is optional. When provided, `persist_messages` writes the latest
    message snapshot to SQLite (debug only — the snapshot is not reloaded on
    startup; per plan §1.2.3 the simplified scheme is "refresh = expired").
    """

    def __init__(self, output_dir: Path, db_path: Path | None = None):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self.output_dir = output_dir
        self.db_path = db_path

    def get_or_create(self, session_id: str) -> Session:
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing and not existing.is_expired():
                existing.touch()
                return existing
            if existing:
                self._sessions.pop(session_id, None)
            session = Session(session_id, self.output_dir)
            self._load_workflow(session)
            self._sessions[session_id] = session
            return session

    def _load_workflow(self, session: Session) -> None:
        """Rehydrate graph + stage after an eviction or a process restart."""
        if self.db_path is None:
            return
        from ..db import get_workflow

        saved = get_workflow(self.db_path, session.session_id)
        if saved:
            session.graph = saved["graph"]
            session.stage = saved["stage"]

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if session.is_expired():
                self._sessions.pop(session_id, None)
                return None
            session.touch()
            return session

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> int:
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
            for sid in expired:
                self._sessions.pop(sid, None)
            return len(expired)

    def persist_messages(self, session: Session) -> None:
        """Write the session's message history to SQLite. No-op if no db_path."""
        if self.db_path is None:
            return
        # Local import keeps the module light and avoids an import cycle at load.
        from ..db import save_session_messages

        save_session_messages(
            self.db_path,
            session.session_id,
            list(session.messages),
            ui_messages=list(session.ui_messages),
        )

    def persist_workflow(self, session: Session) -> None:
        """Write the session's graph + stage to SQLite. No-op without a graph."""
        if self.db_path is None or session.graph is None:
            return
        from ..db import save_workflow

        save_workflow(self.db_path, session.session_id, session.graph, session.stage)


# Module-level singleton; the FastAPI app wires the output_dir at startup.
_session_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        with _store_lock:
            if _session_store is None:
                from ..config import get_settings

                base = Path(get_settings().APP_DATA_DIR).resolve()
                outputs = base / "outputs"
                outputs.mkdir(parents=True, exist_ok=True)
                db_path = base / "metadata.db"
                _session_store = SessionStore(outputs, db_path=db_path)
    return _session_store


def reset_session_store() -> None:
    """Test hook: clear the singleton so a new one is built with the new APP_DATA_DIR."""
    global _session_store
    with _store_lock:
        _session_store = None