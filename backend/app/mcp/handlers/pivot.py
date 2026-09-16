"""tablex_pivot handler."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ...db import OutputRecord, init_db, insert_output
from ...domain.pivot import crosstab, pivot_table, unpivot
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _db_path, _fail, _ok, _write_export_workbook

_OPERATION_DISPATCH = {
    "pivot": lambda df, kw: pivot_table(df, **kw),
    "unpivot": lambda df, kw: unpivot(df, **kw),
    "crosstab": lambda df, kw: crosstab(df, **kw),
}


def handle_pivot(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    operation = tool_call.input.get("operation", "pivot")
    sheet_ref = f"{file_id}::{sheet}"
    if sheet_ref not in session.tables:
        return _fail(f"工作表未加载: {sheet_ref}")
    df = session.tables[sheet_ref]

    if operation not in _OPERATION_DISPATCH:
        return _fail(f"不支持的操作: {operation}")

    index = tool_call.input.get("index") or []
    columns = tool_call.input.get("columns") or []
    values = tool_call.input.get("values")
    aggfunc = tool_call.input.get("aggfunc", "sum")
    fill_value = tool_call.input.get("fill_value", 0)
    var_name = tool_call.input.get("var_name", "variable")
    value_name = tool_call.input.get("value_name", "value")

    if operation == "pivot":
        if not index or not columns:
            return _fail("pivot 操作必须提供 index 和 columns")
        kw = {
            "index": index,
            "columns": columns,
            "values": values,
            "aggfunc": aggfunc,
            "fill_value": fill_value,
        }
    elif operation == "unpivot":
        if not index:
            return _fail("unpivot 操作必须提供 index")
        kw = {
            "index": index,
            "var_name": var_name,
            "value_name": value_name,
        }
    else:
        if not index or not columns:
            return _fail("crosstab 操作必须提供 index 和 columns")
        kw = {
            "index": index,
            "columns": columns,
            "values": values,
            "aggfunc": aggfunc,
            "fill_value": fill_value,
        }

    try:
        result_df = _OPERATION_DISPATCH[operation](df, kw)
    except (ValueError, KeyError) as exc:
        return _fail(f"{operation} 失败: {exc}")

    output_sheet = f"{operation}_结果"
    session.tables[output_sheet] = result_df

    output_id = uuid.uuid4().hex
    output_path = session.output_dir / f"{output_id}.xlsx"
    tables_for_export = dict(session.tables)
    tables_for_export[output_sheet] = result_df
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
            plan={"tool": "tablex_pivot", "input": tool_call.input},
            result={"rows": int(len(result_df)), "operation": operation},
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    _audit(
        session, f"pivot_{operation}", sheet_ref,
        list(result_df.columns),
        len(df), len(result_df), [],
        {"operation": operation, "index": index, "columns": columns, "aggfunc": aggfunc},
    )

    return _ok(
        f"{operation} 完成：输出 {len(result_df)} 行 × {len(result_df.columns)} 列",
        data={
            "output_id": output_id,
            "output_sheet": output_sheet,
            "operation": operation,
            "rows": int(len(result_df)),
            "columns": int(len(result_df.columns)),
        },
    )


HANDLERS = {
    "tablex_pivot": HandlerSpec(
        "tablex_pivot", ["file_id", "sheet", "operation"], handle_pivot,
    ),
}