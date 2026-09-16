"""tablex_group_summary handler."""
from __future__ import annotations

from typing import Any

from ...domain.executor import _apply_group_summary
from ...schemas import GroupSummaryOperation
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_group_summary(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    group_by = tool_call.input["group_by"]
    metrics = tool_call.input["metrics"]
    output_sheet = tool_call.input.get("output_sheet", "汇总结果")
    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables[sheet_ref]

    missing = [c for c in group_by if c not in df.columns]
    if missing:
        return _fail(f"分组列不存在: {missing}")
    for col in metrics.keys():
        if col not in df.columns:
            return _fail(f"聚合列不存在: {col}")

    op = GroupSummaryOperation(
        sheet=sheet_ref, group_by=group_by, metrics=metrics, output_sheet=output_sheet,
    )
    summary = _apply_group_summary(df, op)
    session.tables[output_sheet] = summary
    _audit(
        session, "group_summary", sheet_ref,
        list({*group_by, *metrics.keys()}), len(df), len(summary), [],
        {"group_by": group_by, "metrics": metrics, "output_sheet": output_sheet},
    )
    return _ok(
        f"已按 {', '.join(group_by)} 汇总为 {len(summary)} 组，写入 '{output_sheet}'",
        data={"output_sheet": output_sheet, "group_count": len(summary)},
    )


HANDLERS = {
    "tablex_group_summary": HandlerSpec(
        "tablex_group_summary",
        ["file_id", "sheet", "group_by", "metrics"], handle_group_summary,
    ),
}
