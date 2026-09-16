"""tablex_fill_null handler."""
from __future__ import annotations

from typing import Any

from ...domain._archive.operations import InvalidPlanError
from ...domain.executor import _apply_fill_null
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_fill_null(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    column = tool_call.input["column"]
    method = tool_call.input["method"]
    value = tool_call.input.get("value")
    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables[sheet_ref]

    if column not in df.columns:
        return _fail(f"列 {column} 不存在")
    try:
        new_df, affected = _apply_fill_null(df, column=column, method=method, value=value)
    except InvalidPlanError as exc:
        return _fail(str(exc))
    session.tables[sheet_ref] = new_df
    _audit(
        session, "fill_null", sheet_ref, [column], len(df), len(new_df), affected,
        {"column": column, "method": method, "value": value},
    )
    label = {"mean": "均值", "ffill": "前值", "bfill": "后值", "value": "指定值"}.get(method, method)
    return _ok(
        f"已用 {label} 填充 {column} 列的 {len(affected)} 个空值",
        data={"column": column, "method": method, "filled_count": len(affected)},
    )


HANDLERS = {
    "tablex_fill_null": HandlerSpec(
        "tablex_fill_null", ["file_id", "sheet", "column", "method"], handle_fill_null,
    ),
}
