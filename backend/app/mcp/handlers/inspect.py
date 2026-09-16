"""tablex_inspect handler."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...domain.parser import inspect_workbook
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _fail, _ok


def handle_inspect(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet_name = tool_call.input.get("sheet")
    path = Path(session.files[file_id]["path"])
    try:
        inspection = inspect_workbook(path)
    except Exception as exc:
        return _fail(f"无法检查文件: {exc}")

    target = None
    if sheet_name:
        target = next((s for s in inspection.sheets if s.name == sheet_name), None)
        if target is None:
            return _fail(f"工作表不存在: {sheet_name}")
    elif inspection.sheets:
        target = inspection.sheets[0]

    if target is None:
        return _ok("文件没有任何工作表", data={"issues": []})

    issues = [
        {"code": i.code, "severity": i.severity, "message": i.message, "column": i.column}
        for i in target.issues
    ]
    summary = (
        f"工作表 '{target.name}': {target.row_count} 行 × {target.column_count} 列，"
        f"发现 {len(issues)} 个问题"
    )
    return _ok(
        summary,
        data={
            "sheet": target.name,
            "row_count": target.row_count,
            "column_count": target.column_count,
            "columns": [
                {"name": c.name, "type": c.inferred_type, "null_count": c.null_count}
                for c in target.columns
            ],
            "issues": issues[:20],
        },
    )


HANDLERS = {
    "tablex_inspect": HandlerSpec("tablex_inspect", ["file_id"], handle_inspect),
}
