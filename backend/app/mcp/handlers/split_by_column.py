"""tablex_split_by_column handler.

Splits a sheet into multiple sheets based on the unique values of a column.
"""
from __future__ import annotations

from typing import Any

from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _fail, _ok


def _sanitize_sheet_name(raw: str, taken: set[str], idx: int) -> str:
    cleaned = (
        str(raw).replace(":", "_").replace("\\", "_").replace("/", "_")
        .replace("?", "_").replace("*", "_").replace("[", "_").replace("]", "_")
        .strip()
    ) or "group"
    candidate = cleaned[:31]
    suffix = 1
    while candidate in taken:
        suffix += 1
        stem = cleaned[: max(0, 31 - len(str(suffix)) - 1)]
        candidate = f"{stem}_{suffix}"
    taken.add(candidate)
    return candidate


def handle_split_by_column(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    group_column = tool_call.input["group_column"]
    output_name = tool_call.input.get("output_name")
    if not output_name:
        return _fail("output_name 是必填参数")

    sheet_ref = f"{file_id}::{sheet}"
    df = session.tables.get(sheet_ref)
    if df is None:
        return _fail(f"工作表未加载: {sheet_ref}")

    if group_column not in df.columns:
        return _fail(f"列 '{group_column}' 不存在")

    unique_values = df[group_column].dropna().unique().tolist()
    if not unique_values:
        return _fail(f"列 '{group_column}' 全为空，无可拆分的分组")

    taken: set[str] = set(session.tables.keys())
    created: list[str] = []
    for value in unique_values:
        name = _sanitize_sheet_name(value, taken, len(created))
        subset = df[df[group_column] == value].reset_index(drop=True)
        session.tables[name] = subset
        created.append(name)

    _audit(
        session, "split_by_column", sheet_ref,
        [group_column], len(df), sum(len(session.tables[n]) for n in created),
        [],
        {"group_column": group_column, "sheets": created},
    )

    preview = ", ".join(created[:5]) + ("..." if len(created) > 5 else "")
    return _ok(
        f"按 '{group_column}' 拆分为 {len(created)} 个 sheet: {preview}",
        data={"output_name": output_name, "sheets": created},
    )


HANDLERS = {
    "tablex_split_by_column": HandlerSpec(
        "tablex_split_by_column", ["file_id", "sheet", "group_column", "output_name"],
        handle_split_by_column,
    ),
}