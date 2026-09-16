"""tablex_deduplicate handler."""
from __future__ import annotations

from typing import Any

from ...domain.executor import _apply_deduplicate
from ...schemas import DeduplicateOperation
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def handle_deduplicate(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    key_columns = tool_call.input["key_columns"]
    keep = tool_call.input.get("keep", "first")
    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables[sheet_ref]

    missing = [c for c in key_columns if c not in df.columns]
    if missing:
        return _fail(f"列不存在: {missing}")

    op = DeduplicateOperation(sheet=sheet_ref, key_columns=key_columns, keep=keep)
    new_df, affected = _apply_deduplicate(df, op)
    removed = len(df) - len(new_df)
    session.tables[sheet_ref] = new_df
    _audit(
        session, "deduplicate", sheet_ref, key_columns, len(df), len(new_df), affected,
        {"keep": keep, "removed": removed},
    )
    return _ok(
        f"删除 {removed} 行重复数据（基于 {', '.join(key_columns)}）",
        data={"removed_rows": affected[:20], "input_rows": len(df), "output_rows": len(new_df)},
    )


HANDLERS = {
    "tablex_deduplicate": HandlerSpec(
        "tablex_deduplicate", ["file_id", "sheet", "key_columns"], handle_deduplicate,
    ),
}
