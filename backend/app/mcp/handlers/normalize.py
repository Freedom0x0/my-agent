"""tablex_normalize handler."""
from __future__ import annotations

from typing import Any

from ...domain.executor import _apply_normalize
from ...schemas import NormalizeOperation
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_normalize(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    columns = tool_call.input["columns"]
    target_type = tool_call.input["target_type"]
    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables[sheet_ref]

    missing = [c for c in columns if c not in df.columns]
    if missing:
        return _fail(f"列不存在: {missing}")

    op = NormalizeOperation(sheet=sheet_ref, columns=columns, target_type=target_type)
    new_df, affected = _apply_normalize(df, op)
    session.tables[sheet_ref] = new_df
    _audit(session, "normalize", sheet_ref, columns, len(df), len(new_df), affected, {"target_type": target_type})
    return _ok(
        f"已统一 {len(columns)} 列格式，影响 {len(affected)} 行",
        data={"columns": columns, "affected_rows": affected[:20]},
    )


HANDLERS = {
    "tablex_normalize": HandlerSpec(
        "tablex_normalize", ["file_id", "sheet", "columns", "target_type"], handle_normalize,
    ),
}
