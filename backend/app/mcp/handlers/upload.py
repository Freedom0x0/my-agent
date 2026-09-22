"""tablex_upload handler."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...domain.parser import inspect_workbook, load_tables
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _fail, _ok


def handle_upload(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    requested_sheet = tool_call.input.get("sheet")
    info = session.files[file_id]
    path = Path(info["path"])
    if not path.exists():
        return _fail(f"文件已不存在: {path}")
    try:
        inspection = inspect_workbook(path)
        tables = load_tables(path)
    except Exception as exc:
        return _fail(f"无法解析文件: {exc}")

    if requested_sheet is not None and requested_sheet not in tables:
        return _fail(f"工作表不存在: {requested_sheet}")

    selected_tables = (
        {requested_sheet: tables[requested_sheet]}
        if requested_sheet is not None
        else tables
    )
    loaded: list[str] = []
    for sheet_name, df in selected_tables.items():
        ref = f"{file_id}::{sheet_name}"
        session.tables[ref] = df
        loaded.append(sheet_name)

    issue_count = sum(len(s.issues) for s in inspection.sheets)
    summary = f"已加载 {inspection.filename} 的 {len(loaded)} 个工作表，发现 {issue_count} 个数据质量问题"
    return _ok(
        summary,
        data={
            "file_id": file_id,
            "sheets": loaded,
            "loaded_refs": [f"{file_id}::{n}" for n in loaded],
            "issue_count": issue_count,
        },
    )


HANDLERS = {
    "tablex_upload": HandlerSpec("tablex_upload", ["file_id"], handle_upload),
}
