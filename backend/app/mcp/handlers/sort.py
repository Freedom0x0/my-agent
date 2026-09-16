"""tablex_sort handler."""
from __future__ import annotations

from typing import Any

from ...domain._archive.operations import InvalidPlanError
from ...domain.executor import _apply_sort
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_sort(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    column = tool_call.input["column"]
    order = tool_call.input.get("order", "asc")
    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables[sheet_ref]

    if column not in df.columns:
        return _fail(f"列 {column} 不存在")
    try:
        new_df, affected = _apply_sort(df, column=column, order=order)
    except InvalidPlanError as exc:
        return _fail(str(exc))
    session.tables[sheet_ref] = new_df
    _audit(
        session, "sort", sheet_ref, [column], len(df), len(new_df), affected,
        {"column": column, "order": order},
    )
    label = "降序" if order == "desc" else "升序"
    return _ok(f"已按 {column} {label}排序", data={"column": column, "order": order})


HANDLERS = {
    "tablex_sort": HandlerSpec(
        "tablex_sort", ["file_id", "sheet", "column"], handle_sort,
    ),
}
