"""tablex_filter handler."""
from __future__ import annotations

from typing import Any

from ...domain.executor import _apply_filter
from ...schemas import FilterCondition, FilterOperation
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_filter(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    conditions_raw = tool_call.input["conditions"]
    match = tool_call.input.get("match", "all")
    output_sheet = tool_call.input.get("output_sheet")
    if not output_sheet:
        return _fail("output_sheet 是必填参数，请指定唯一名字")
    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables[sheet_ref]

    if output_sheet in session.tables:
        return _fail(f"output_sheet '{output_sheet}' 已存在，请换名（多次调用 filter 必须用不同名字）")

    conditions = []
    for c in conditions_raw:
        try:
            conditions.append(FilterCondition.model_validate(c))
        except Exception as exc:
            return _fail(f"筛选条件无效: {exc}")
        if conditions[-1].column not in df.columns:
            return _fail(f"列 {conditions[-1].column} 不存在")

    op = FilterOperation(
        sheet=sheet_ref, conditions=conditions, match=match, output_sheet=output_sheet,
    )
    filtered = _apply_filter(df, op)
    session.tables[output_sheet] = filtered
    _audit(
        session, "filter", sheet_ref,
        [c.column for c in conditions], len(df), len(filtered), [],
        {"conditions": [c.model_dump() for c in conditions], "match": match, "output_sheet": output_sheet},
    )
    return _ok(
        f"筛选出 {len(filtered)} 条记录，写入工作表 '{output_sheet}'",
        data={"output_sheet": output_sheet, "matched": len(filtered)},
    )


HANDLERS = {
    "tablex_filter": HandlerSpec(
        "tablex_filter", ["file_id", "sheet", "conditions"], handle_filter,
    ),
}
