"""tablex_fill_formula handler."""
from __future__ import annotations

from typing import Any

from ...domain._archive.operations import InvalidPlanError
from ...domain.executor import _apply_fill_formula
from ...schemas import FillFormulaOperation
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_fill_formula(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    target_column = tool_call.input["target_column"]
    expression = tool_call.input["expression"]
    start_row = int(tool_call.input["start_row"])
    end_row = int(tool_call.input["end_row"])
    only_blank = bool(tool_call.input.get("only_blank", True))
    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables[sheet_ref]

    if target_column not in df.columns:
        return _fail(f"目标列 {target_column} 不存在")
    if start_row > end_row:
        return _fail("起始行不能大于结束行")

    op = FillFormulaOperation(
        sheet=sheet_ref, target_column=target_column, expression=expression,
        start_row=start_row, end_row=end_row, only_blank=only_blank,
    )
    try:
        new_df, affected = _apply_fill_formula(df, op)
    except InvalidPlanError as exc:
        return _fail(str(exc))
    session.tables[sheet_ref] = new_df
    _audit(
        session, "fill_formula", sheet_ref, [target_column], len(df), len(new_df), affected,
        {"expression": expression, "range": [start_row, end_row], "only_blank": only_blank},
    )
    return _ok(
        f"已为 {target_column} 列补充 {len(affected)} 个公式",
        data={"target_column": target_column, "affected_rows": affected[:20]},
    )


HANDLERS = {
    "tablex_fill_formula": HandlerSpec(
        "tablex_fill_formula",
        ["file_id", "sheet", "target_column", "expression", "start_row", "end_row"],
        handle_fill_formula,
    ),
}
