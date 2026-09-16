"""tablex_join handler."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ...db import OutputRecord, init_db, insert_output
from ...domain.joiner import JoinError, join_tables
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _db_path, _fail, _ok, _write_export_workbook


def handle_join(tool_call: ToolCall, session: Any) -> ToolResult:
    left_ref_in = tool_call.input["left"]
    right_ref_in = tool_call.input["right"]
    on = tool_call.input.get("on")
    left_on = tool_call.input.get("left_on")
    right_on = tool_call.input.get("right_on")
    how = tool_call.input.get("how", "inner")
    suffix_list = tool_call.input.get("suffix") or ["_l", "_r"]
    suffix = (suffix_list[0], suffix_list[1]) if len(suffix_list) >= 2 else ("_l", "_r")

    if on and (left_on or right_on):
        return _fail("on 与 left_on/right_on 不能同时提供")
    if not on and not (left_on and right_on):
        return _fail("必须提供 on 或 left_on+right_on")

    left_sheet = f"{left_ref_in['file_id']}::{left_ref_in['sheet']}"
    right_sheet = f"{right_ref_in['file_id']}::{right_ref_in['sheet']}"
    if left_sheet not in session.tables:
        return _fail(f"工作表未加载: {left_sheet}")
    if right_sheet not in session.tables:
        return _fail(f"工作表未加载: {right_sheet}")

    left_df = session.tables[left_sheet]
    right_df = session.tables[right_sheet]

    try:
        merged, meta = join_tables(
            left_df, right_df,
            on=on, left_on=left_on, right_on=right_on,
            how=how, suffix=suffix,
        )
    except JoinError as exc:
        return _fail(str(exc))

    output_sheet = "join结果"
    session.tables[output_sheet] = merged

    output_id = uuid.uuid4().hex
    output_path = session.output_dir / f"{output_id}.xlsx"
    tables_for_export = dict(session.tables)
    tables_for_export[output_sheet] = merged
    _write_export_workbook(output_path, tables_for_export, session.audit_events)

    session.output_id = output_id
    session.output_path = str(output_path)

    db_path = _db_path()
    init_db(db_path)
    insert_output(
        db_path,
        OutputRecord(
            output_id=output_id,
            stored_path=str(output_path),
            source_file_ids=list(session.files.keys()),
            plan={"tool": "tablex_join", "input": tool_call.input},
            result={"rows": int(len(merged)), "meta": meta.__dict__},
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    _audit(
        session, "join", f"{left_sheet},{right_sheet}",
        [on or left_on],
        meta.left_count + meta.right_count,
        len(merged), [],
        {"how": how, "matched": meta.matched, "unmatched_left": meta.unmatched_left, "unmatched_right": meta.unmatched_right},
    )

    summary = (
        f"join 完成：输出 {len(merged)} 行，匹配 {meta.matched} 条，"
        f"未匹配 左{meta.unmatched_left}/右{meta.unmatched_right}"
    )
    return _ok(
        summary,
        data={
            "output_id": output_id,
            "output_sheet": output_sheet,
            "rows": int(len(merged)),
            "meta": meta.__dict__,
        },
    )


HANDLERS = {
    "tablex_join": HandlerSpec(
        "tablex_join", ["left", "right"], handle_join,
    ),
}