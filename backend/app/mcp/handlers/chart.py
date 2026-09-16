"""tablex_chart handler."""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Any

from ...db import OutputRecord, init_db, insert_output
from ...domain.chart import (
    ChartError, auto_select_chart, embed_in_excel, generate_chart,
)
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _db_path, _fail, _ok, _write_export_workbook


def handle_chart(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    chart_type = tool_call.input.get("chart_type", "auto")
    x = tool_call.input["x"]
    y = tool_call.input["y"] or []
    title = tool_call.input.get("title")
    style = tool_call.input.get("style") or {}

    if not y:
        return _fail("y 列表不能为空")

    sheet_ref = f"{file_id}::{sheet}"
    if sheet_ref not in session.tables:
        return _fail(f"工作表未加载: {sheet_ref}")
    df = session.tables[sheet_ref]

    try:
        actual_type = auto_select_chart(df, x, y) if chart_type == "auto" else chart_type
        png_bytes = generate_chart(
            df, chart_type=actual_type, x=x, y=y, title=title, style=style,
        )
    except ChartError as exc:
        return _fail(str(exc))

    output_id = uuid.uuid4().hex
    output_path = session.output_dir / f"{output_id}.xlsx"
    tables_for_export = dict(session.tables)
    _write_export_workbook(output_path, tables_for_export, session.audit_events)
    embed_in_excel(output_path, png_bytes, sheet_name="图表")

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
            plan={"tool": "tablex_chart", "input": tool_call.input},
            result={"chart_type": actual_type, "png_base64": base64.b64encode(png_bytes).decode("ascii")},
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    _audit(
        session, "chart", sheet_ref,
        [x, *y],
        len(df), len(df), [],
        {"chart_type": actual_type, "x": x, "y": y, "title": title},
    )

    return _ok(
        f"图表已生成（{actual_type}）",
        data={
            "output_id": output_id,
            "chart_type": actual_type,
            "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        },
    )


HANDLERS = {
    "tablex_chart": HandlerSpec(
        "tablex_chart", ["file_id", "sheet", "x", "y"], handle_chart,
    ),
}