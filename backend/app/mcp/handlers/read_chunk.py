"""tablex_read_chunk handler."""
from __future__ import annotations

from typing import Any

from ...domain.streaming import read_chunk, total_rows
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _fail, _ok


def handle_read_chunk(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    offset = int(tool_call.input.get("offset", 0))
    limit = int(tool_call.input.get("limit", 1000))
    columns = tool_call.input.get("columns")

    sheet_ref = f"{file_id}::{sheet}"
    if sheet_ref not in session.tables:
        return _fail(f"工作表未加载: {sheet_ref}")
    df = session.tables[sheet_ref]

    try:
        chunk = read_chunk(df, offset=offset, limit=limit, columns=columns)
    except (ValueError, KeyError) as exc:
        return _fail(str(exc))

    summary = f"返回 {len(chunk)} 行" + (f"，列：{columns}" if columns else "")
    return _ok(
        summary,
        data={
            "rows": chunk.to_dict(orient="records"),
            "total_rows": total_rows(df),
            "offset": offset,
            "limit": limit,
            "returned": len(chunk),
        },
    )


HANDLERS = {
    "tablex_read_chunk": HandlerSpec(
        "tablex_read_chunk", ["file_id", "sheet"], handle_read_chunk,
    ),
}
