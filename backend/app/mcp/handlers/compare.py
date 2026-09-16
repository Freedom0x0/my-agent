"""tablex_compare handler."""
from __future__ import annotations

from typing import Any

from ...domain._archive.operations import InvalidPlanError
from ...domain.executor import _apply_compare
from ...schemas import CompareOperation
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_compare(tool_call: ToolCall, session: Any) -> ToolResult:
    left_ref = tool_call.input["left_ref"]
    right_ref = tool_call.input["right_ref"]
    key_columns = tool_call.input["key_columns"]
    output_sheet = tool_call.input.get("output_sheet", "对比结果")

    if left_ref not in session.tables:
        return _fail(f"工作表未加载: {left_ref}")
    if right_ref not in session.tables:
        return _fail(f"工作表未加载: {right_ref}")

    left = session.tables[left_ref]
    right = session.tables[right_ref]
    op = CompareOperation(
        left_sheet=left_ref, right_sheet=right_ref, key_columns=key_columns,
        compare_columns=None, output_sheet=output_sheet,
    )
    try:
        result_df = _apply_compare(left, right, op)
    except InvalidPlanError as exc:
        return _fail(str(exc))
    session.tables[output_sheet] = result_df

    counts = result_df["变化类型"].value_counts().to_dict() if "变化类型" in result_df.columns else {}
    added = int(counts.get("added", 0))
    removed = int(counts.get("removed", 0))
    changed = int(counts.get("changed", 0))
    _audit(
        session, "compare", f"{left_ref},{right_ref}", key_columns,
        len(left), len(result_df), [],
        {"left_ref": left_ref, "right_ref": right_ref, "key_columns": key_columns, "output_sheet": output_sheet},
    )
    return _ok(
        f"对比完成：新增 {added} 条、删除 {removed} 条、变化 {changed} 条",
        data={"output_sheet": output_sheet, "added": added, "removed": removed, "changed": changed},
    )


HANDLERS = {
    "tablex_compare": HandlerSpec(
        "tablex_compare", ["left_ref", "right_ref", "key_columns"], handle_compare,
    ),
}
