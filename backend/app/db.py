"""SQLite metadata helpers."""
from __future__ import annotations

import json
import sqlite3
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