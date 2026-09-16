"""tablex_decrypt handler."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...db import OutputRecord, init_db, insert_output
from ...domain.decrypt import DecryptError, decrypt_workbook
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _db_path, _fail, _ok, _write_export_workbook


def handle_decrypt(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    password = tool_call.input.get("password", "")

    if file_id not in session.files:
        return _fail(f"文件不存在: {file_id}")
    if not password:
        return _fail("缺少参数: password")

    src_path = Path(session.files[file_id]["path"])
    try:
        sheets = decrypt_workbook(src_path, password)
    except DecryptError as exc:
        return _fail(str(exc), summary="解密失败")

    output_id = uuid.uuid4().hex
    output_path = session.output_dir / f"{output_id}.xlsx"
    _write_export_workbook(output_path, sheets, [])

    # Re-inject into session.tables keyed by new file_id so the user can keep
    # working with the decrypted content directly.
    for sheet_name, df in sheets.items():
        session.tables[f"{output_id}::{sheet_name}"] = df

    session.output_id = output_id
    session.output_path = str(output_path)

    db_path = _db_path()
    init_db(db_path)
    insert_output(
        db_path,
        OutputRecord(
            output_id=output_id,
            stored_path=str(output_path),
            source_file_ids=[file_id],
            plan={"tool": "tablex_decrypt", "input": tool_call.input},
            result={"sheet_names": list(sheets.keys())},
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    _audit(
        session, "decrypt", f"{file_id}::*",
        [], 0, sum(len(df) for df in sheets.values()),
        [],
        {"source_file_id": file_id, "sheet_names": list(sheets.keys())},
    )

    return _ok(
        f"解密成功，共 {len(sheets)} 个工作表",
        data={
            "output_id": output_id,
            "file_id": output_id,
            "sheet_names": list(sheets.keys()),
        },
    )


HANDLERS = {
    "tablex_decrypt": HandlerSpec(
        "tablex_decrypt", ["file_id", "password"], handle_decrypt,
    ),
}
