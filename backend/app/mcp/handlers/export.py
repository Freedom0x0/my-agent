"""tablex_export handler."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ...db import OutputRecord, init_db, insert_output
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _db_path, _fail, _ok, _write_export_workbook


def handle_export(tool_call: ToolCall, session: Any) -> ToolResult:
    if not session.tables:
        return _fail("当前会话没有任何工作表可以导出")

    output_id = uuid.uuid4().hex
    output_path = session.output_dir / f"{output_id}.xlsx"
    _write_export_workbook(output_path, session.tables, session.audit_events)

    session.output_id = output_id
    session.output_path = str(output_path)

    db_path = _db_path()
    init_db(db_path)
    record = OutputRecord(
        output_id=output_id,
        stored_path=str(output_path),
        source_file_ids=list(session.files.keys()),
        plan={"tool_calls": session.tool_calls_log},
        result={
            "audit_events": [e.model_dump() for e in session.audit_events],
            "sheets": list(session.tables.keys()),
        },
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    insert_output(db_path, record)

    sheets = list(session.tables.keys())
    return _ok(
        f"已生成处理结果文件，共 {len(sheets)} 个工作表",
        data={"output_id": output_id, "sheets": sheets + ["_audit"]},
    )


HANDLERS = {
    "tablex_export": HandlerSpec("tablex_export", [], handle_export),
}
