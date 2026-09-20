"""tablex_validate handler."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...db import OutputRecord, init_db, insert_output
from ...domain.validator import ValidationError, validate
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _audit, _db_path, _fail, _ok, _write_export_workbook, _output_id


def handle_validate(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    rules = tool_call.input.get("rules") or []
    fail_strategy = tool_call.input.get("fail_strategy", "report_only")

    if fail_strategy not in {"report_only", "mark", "filter"}:
        return _fail(f"不支持的 fail_strategy: {fail_strategy}")
    if not rules:
        return _fail("rules 不能为空")

    sheet_ref = f"{file_id}::{sheet}"
    if sheet_ref not in session.tables:
        return _fail(f"工作表未加载: {sheet_ref}")
    df = session.tables[sheet_ref]

    try:
        results = validate(df, rules)
    except ValidationError as exc:
        return _fail(str(exc))

    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)
    rule_payload = [r.to_dict() for r in results]

    if fail_strategy == "report_only":
        _audit(
            session, "validate", sheet_ref,
            [r.column for r in results],
            len(df), len(df), [],
            {"rules": rule_payload, "fail_strategy": fail_strategy},
        )
        summary = f"校验完成：通过 {total_passed} 项，失败 {total_failed} 项"
        return _ok(
            summary,
            data={
                "passed": total_passed,
                "failed": total_failed,
                "results": rule_payload,
            },
        )

    # mark / filter: build new sheet
    new_df = df.copy()
    for rule, result in zip(rules, results):
        col_name = f"_validation_{rule['column']}_{rule['type']}"
        flags = ["pass"] * len(new_df)
        for ridx in result.failed_rows:
            if ridx in new_df.index:
                flags[new_df.index.get_loc(ridx)] = "fail"
        new_df[col_name] = flags

    if fail_strategy == "filter":
        passing_mask = new_df[[f"_validation_{r['column']}_{r['type']}" for r in rules]].apply(
            lambda row: all(v == "pass" for v in row), axis=1,
        )
        new_df = new_df.loc[passing_mask].reset_index(drop=True)
        out_sheet_name = "validate_filtered"
    else:
        out_sheet_name = "validate_marked"

    session.tables[out_sheet_name] = new_df

    output_id = _output_id(session)
    output_path = session.output_dir / f"{output_id}.xlsx"
    tables_for_export = dict(session.tables)
    tables_for_export[out_sheet_name] = new_df
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
            plan={"tool": "tablex_validate", "input": tool_call.input},
            result={"passed": total_passed, "failed": total_failed, "fail_strategy": fail_strategy},
            status="completed",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
    )

    _audit(
        session, f"validate_{fail_strategy}", sheet_ref,
        [r.column for r in results],
        len(df), len(new_df), [],
        {"rules": rule_payload, "fail_strategy": fail_strategy},
    )

    action = "过滤后" if fail_strategy == "filter" else "标记后"
    return _ok(
        f"校验完成：{action}保留 {len(new_df)} 行，通过 {total_passed} 项，失败 {total_failed} 项",
        data={
            "output_id": output_id,
            "output_sheet": out_sheet_name,
            "rows": int(len(new_df)),
            "passed": total_passed,
            "failed": total_failed,
            "results": rule_payload,
        },
    )


HANDLERS = {
    "tablex_validate": HandlerSpec(
        "tablex_validate", ["file_id", "sheet", "rules"], handle_validate,
    ),
}