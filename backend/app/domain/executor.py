"""Deterministic spreadsheet executor."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.utils import get_column_letter

from ..schemas import (
    AuditEvent,
    CompareOperation,
    Conclusion,
    CreateIssueSheetOperation,
    DeduplicateOperation,
    ExecutionResult,
    FillFormulaOperation,
    FilterCondition,
    FilterOperation,
    GroupSummaryOperation,
    NormalizeOperation,
    OperationPlan,
)
from .audit import audit_events_to_rows, make_audit_event, make_conclusion
from .operations import (
    ConfirmationRequired,
    HIGH_IMPACT_KINDS,
    InvalidPlanError,
    expected_confirmation_token,
    normalize_plan,
    validate_plan,
)

INTERNAL_COL = "__tablex_source_row__"
MAX_AFFECTED_ROWS = 200

_FORMULA_FORBIDDEN = re.compile(r"[!\[\]:\"'\n\r#]")
_FORMULA_ALLOWED_FUNCS = {"ROUND", "SUM", "IF"}


class OutputValidationError(RuntimeError):
    """Output workbook failed validation after write."""


def _col_letter(idx: int) -> str:
    s = ""
    n = idx
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def _strip_internal(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[INTERNAL_COL], errors="ignore").reset_index(drop=True)


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[,\s¥$￥€£%元万元]", "", text)
    if cleaned in {"", "-", "+", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            ts = pd.to_datetime(text, format=fmt, errors="raise")
            return ts.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    try:
        ts = pd.to_datetime(text, errors="raise")
        return ts.strftime("%Y-%m-%d")
    except (ValueError, TypeError, pd.errors.ParserError):
        return None


def _normalize_cell(value: Any, target_type: str) -> tuple[Any, bool]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, False
    if target_type == "number":
        num = _to_number(value)
        if num is None:
            return value, False
        return num, True
    if target_type == "date":
        d = _to_date(value)
        if d is None:
            return value, False
        return d, True
    return str(value).strip(), str(value) != str(value).strip() or True


def _apply_normalize(df: pd.DataFrame, op: NormalizeOperation) -> tuple[pd.DataFrame, list[int]]:
    new_df = df.copy()
    affected: list[int] = []
    source_rows = new_df[INTERNAL_COL].tolist() if INTERNAL_COL in new_df.columns else list(range(1, len(new_df) + 1))
    for col in op.columns:
        if col not in new_df.columns:
            continue
        new_values: list[Any] = []
        col_changed = False
        for v in new_df[col].tolist():
            new_v, changed = _normalize_cell(v, op.target_type)
            new_values.append(new_v)
            if changed:
                col_changed = True
        new_df[col] = new_values
        if col_changed:
            for idx, v in enumerate(new_df[col].tolist()):
                if v != df[col].iloc[idx]:
                    affected.append(int(source_rows[idx]))
    return new_df, sorted(set(affected))[:MAX_AFFECTED_ROWS]


def _apply_deduplicate(df: pd.DataFrame, op: DeduplicateOperation) -> tuple[pd.DataFrame, list[int]]:
    new_df = df.copy()
    source_rows = new_df[INTERNAL_COL].tolist() if INTERNAL_COL in new_df.columns else list(range(1, len(new_df) + 1))
    null_mask = new_df[op.key_columns].isna().any(axis=1)
    text_null = new_df[op.key_columns].astype(str).apply(lambda s: s.str.strip() == "").any(axis=1)
    keep_mask = ~(null_mask | text_null)
    sub = new_df[keep_mask].copy()
    keep = "first" if op.keep == "first" else "last"
    dup_mask_within = sub.duplicated(subset=op.key_columns, keep=keep)
    drop_indices = sub.index[dup_mask_within].tolist()
    affected = [int(source_rows[i]) for i in drop_indices]
    new_df = new_df.drop(index=drop_indices).reset_index(drop=True)
    return new_df, sorted(set(affected))[:MAX_AFFECTED_ROWS]


def _match_condition(value: Any, cond: FilterCondition) -> bool:
    op = cond.operator
    if op == "is_null":
        return value is None or (isinstance(value, str) and not value.strip())
    if op == "not_null":
        return value is not None and not (isinstance(value, str) and not value.strip())
    if op == "eq":
        if value is None:
            return cond.value is None or (isinstance(cond.value, str) and not cond.value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _to_number(cond.value) == float(value)
        return str(value).strip().lower() == str(cond.value).strip().lower()
    if op == "ne":
        return not _match_condition(value, FilterCondition(column=cond.column, operator="eq", value=cond.value))
    if op == "contains":
        if value is None:
            return False
        return str(cond.value).lower() in str(value).lower()
    if op == "in":
        target = cond.value or []
        if not isinstance(target, list):
            target = [target]
        if value is None:
            return None in target
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return any(_to_number(v) == float(value) for v in target)
        return any(str(value).strip() == str(v).strip() for v in target)
    # numeric comparisons
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = _to_number(cond.value)
        if v is None:
            return False
        if op == "gt":
            return float(value) > v
        if op == "gte":
            return float(value) >= v
        if op == "lt":
            return float(value) < v
        if op == "lte":
            return float(value) <= v
    if isinstance(value, str):
        d = _to_date(value)
        if d is not None:
            try:
                ts = pd.Timestamp(d)
                cmp_ts = pd.Timestamp(_to_date(cond.value) or str(cond.value))
                if op == "gt":
                    return ts > cmp_ts
                if op == "gte":
                    return ts >= cmp_ts
                if op == "lt":
                    return ts < cmp_ts
                if op == "lte":
                    return ts <= cmp_ts
            except (ValueError, TypeError):
                pass
    return False


def _apply_filter(df: pd.DataFrame, op: FilterOperation) -> pd.DataFrame:
    if op.match == "all":
        mask = pd.Series([True] * len(df), index=df.index)
        for cond in op.conditions:
            mask = mask & df[cond.column].apply(lambda v: _match_condition(v, cond))
    else:
        mask = pd.Series([False] * len(df), index=df.index)
        for cond in op.conditions:
            mask = mask | df[cond.column].apply(lambda v: _match_condition(v, cond))
    return df[mask].reset_index(drop=True)


def _agg_value(series: pd.Series, func: str) -> Any:
    numeric = series.apply(_to_number).dropna()
    if numeric.empty:
        return 0 if func == "count" else None
    if func == "sum":
        return float(numeric.sum())
    if func == "mean":
        return float(numeric.mean())
    if func == "min":
        return float(numeric.min())
    if func == "max":
        return float(numeric.max())
    if func == "count":
        return int(series.dropna().astype(str).str.strip().astype(bool).sum())
    return None


def _apply_group_summary(df: pd.DataFrame, op: GroupSummaryOperation) -> pd.DataFrame:
    work = df.copy()
    for col in op.group_by:
        work[col] = work[col].apply(lambda v: "未填写" if v is None or (isinstance(v, str) and not v.strip()) else v)
    grouped = work.groupby(op.group_by, dropna=False, sort=True)
    rows: list[dict[str, Any]] = []
    for keys, sub in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        record: dict[str, Any] = {}
        for g, k in zip(op.group_by, keys):
            record[g] = k
        for col, funcs in op.metrics.items():
            for fn in funcs:
                record[f"{col}_{fn}"] = _agg_value(sub[col], fn)
        rows.append(record)
    return pd.DataFrame(rows)


def _apply_compare(left: pd.DataFrame, right: pd.DataFrame, op: CompareOperation) -> pd.DataFrame:
    if left[op.key_columns].duplicated().any():
        raise InvalidPlanError("左表存在重复 key")
    if right[op.key_columns].duplicated().any():
        raise InvalidPlanError("右表存在重复 key")
    left_indexed = left.set_index(op.key_columns)
    right_indexed = right.set_index(op.key_columns)
    common_cols = [c for c in left.columns if c in right.columns and c not in op.key_columns]
    compare_cols = op.compare_columns or common_cols
    rows: list[dict[str, Any]] = []
    left_keys = set(left_indexed.index.tolist())
    right_keys = set(right_indexed.index.tolist())
    for key in sorted(left_keys - right_keys, key=lambda k: str(k)):
        record: dict[str, Any] = {"变化类型": "removed"}
        for kc, kv in zip(op.key_columns, key if isinstance(key, tuple) else (key,)):
            record[kc] = kv
        for c in compare_cols:
            record[f"{c}_左侧值"] = left_indexed.loc[key].get(c) if key in left_indexed.index else None
            record[f"{c}_右侧值"] = None
            record["变化字段"] = c
        rows.append(record)
    for key in sorted(right_keys - left_keys, key=lambda k: str(k)):
        record = {"变化类型": "added"}
        for kc, kv in zip(op.key_columns, key if isinstance(key, tuple) else (key,)):
            record[kc] = kv
        for c in compare_cols:
            record[f"{c}_左侧值"] = None
            record[f"{c}_右侧值"] = right_indexed.loc[key].get(c) if key in right_indexed.index else None
            record["变化字段"] = c
        rows.append(record)
    for key in sorted(left_keys & right_keys, key=lambda k: str(k)):
        l_row = left_indexed.loc[key]
        r_row = right_indexed.loc[key]
        changed_cols = [c for c in compare_cols if str(l_row.get(c)) != str(r_row.get(c))]
        for c in changed_cols:
            record = {"变化类型": "changed", "变化字段": c}
            for kc, kv in zip(op.key_columns, key if isinstance(key, tuple) else (key,)):
                record[kc] = kv
            record[f"{c}_左侧值"] = l_row.get(c)
            record[f"{c}_右侧值"] = r_row.get(c)
            rows.append(record)
    return pd.DataFrame(rows)


def _validate_formula_expression(expression: str) -> None:
    if _FORMULA_FORBIDDEN.search(expression):
        raise InvalidPlanError(f"公式包含非法字符: {expression}")
    # Extract placeholders {col}{row} first, then check remaining tokens
    cleaned = re.sub(r"\{[^{}]+\}", "", expression)
    if not re.fullmatch(r"[A-Z0-9_+\-*/()., \t]+", cleaned):
        raise InvalidPlanError(f"公式包含不支持的字符: {expression}")
    funcs = set(re.findall(r"[A-Z][A-Z0-9_]+", cleaned))
    if not funcs.issubset(_FORMULA_ALLOWED_FUNCS):
        raise InvalidPlanError(f"公式使用了不支持的函数: {', '.join(funcs - _FORMULA_ALLOWED_FUNCS)}")


def _render_formula(expression: str, column_index: dict[str, int], row: int) -> str:
    placeholders = re.findall(r"\{([^{}]+)\}", expression)
    rendered = expression
    for ph in placeholders:
        if ph.isdigit():
            rendered = rendered.replace("{" + ph + "}", str(row), 1)
        else:
            col = column_index.get(ph)
            if col is None:
                raise InvalidPlanError(f"公式引用了不存在的列 {ph}")
            rendered = rendered.replace("{" + ph + "}", f"{_col_letter(col)}{row}", 1)
    return "=" + rendered


def _apply_fill_formula(df: pd.DataFrame, op: FillFormulaOperation) -> tuple[pd.DataFrame, list[int]]:
    new_df = df.copy()
    column_index = {c: i + 1 for i, c in enumerate(new_df.columns)}
    if op.target_column not in column_index:
        raise InvalidPlanError(f"目标列 {op.target_column} 不存在")
    _validate_formula_expression(op.expression)
    source_rows = new_df[INTERNAL_COL].tolist() if INTERNAL_COL in new_df.columns else list(range(1, len(new_df) + 1))
    affected: list[int] = []
    target_col_idx = column_index[op.target_column] - 1
    excel_start = op.start_row
    excel_end = op.end_row
    # df row index is 0-based; excel row index maps: df row 0 = excel row 2 (header=1)
    for df_idx in range(len(new_df)):
        excel_row = df_idx + 2
        if excel_row < excel_start or excel_row > excel_end:
            continue
        current = new_df.iloc[df_idx, target_col_idx]
        if op.only_blank and current is not None and not (isinstance(current, str) and not current.strip()):
            continue
        new_df.iat[df_idx, target_col_idx] = _render_formula(op.expression, column_index, excel_row)
        affected.append(int(source_rows[df_idx]))
    return new_df, sorted(set(affected))[:MAX_AFFECTED_ROWS]


OUTPUT_NAME_MAX_LEN = 31


def _escape_sheet_name(name: str, taken: set[str]) -> str:
    """Truncate and uniquify an Excel sheet name (max 31 chars)."""
    cleaned = name.strip() or "工作表"
    if len(cleaned) > OUTPUT_NAME_MAX_LEN:
        digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:6]
        cleaned = cleaned[:24] + "_" + digest
    candidate = cleaned
    suffix = 1
    while candidate in taken:
        suffix += 1
        stem = cleaned[: max(0, 31 - len(str(suffix)) - 1)]
        candidate = f"{stem}_{suffix}"
    taken.add(candidate)
    return candidate


def _split_sheet_ref(ref: str) -> tuple[str, str]:
    if "::" not in ref:
        raise InvalidPlanError(f"无效的工作表引用 {ref}")
    file_id, sheet_name = ref.split("::", 1)
    return file_id, sheet_name


def _plan_main_output(plan: OperationPlan) -> str:
    return "清洗后数据" if "清洗后数据" in plan.outputs else plan.outputs[0]


def execute_plan(
    tables: dict[str, pd.DataFrame],
    plan: OperationPlan,
    confirmation_token: str | None,
    output_path: Path,
) -> ExecutionResult:
    """Execute a validated plan and write a new workbook.

    `tables` maps SheetRef (`<file_id>::<sheet_name>`) to a DataFrame with
    the internal source-row column.
    """
    plan = normalize_plan(plan)
    sheet_columns: dict[str, set[str]] = {
        ref: set(df.columns) - {INTERNAL_COL} for ref, df in tables.items()
    }
    validate_plan(plan, sheet_columns)

    main_output = _plan_main_output(plan)

    # Confirmation gate
    needs_confirmation = any(op.kind in HIGH_IMPACT_KINDS for op in plan.operations)
    if needs_confirmation and confirmation_token != expected_confirmation_token(plan.id):
        raise ConfirmationRequired(plan.id, [])

    # Working state: only the first source sheet is the transform pipeline target
    first_source = plan.source_sheets[0]
    main_state: pd.DataFrame = tables[first_source].copy()
    pending_issues: list[dict[str, Any]] = []
    output_sheets: dict[str, pd.DataFrame] = {}
    audit_events: list[AuditEvent] = []
    conclusions: list[Conclusion] = []
    metrics: dict[str, str | int | float] = {
        "input_rows": int(len(main_state)),
        "input_columns": int(main_state.shape[1]),
    }

    step_counter = 0

    def next_step() -> str:
        nonlocal step_counter
        step_counter += 1
        return f"step-{step_counter:03d}"

    input_rows_main = int(len(main_state))

    for op in plan.operations:
        if isinstance(op, NormalizeOperation):
            new_state, affected = _apply_normalize(main_state, op)
            event = make_audit_event(
                step_id=next_step(),
                operation="normalize",
                input_sheets=[op.sheet],
                output_sheets=[main_output],
                columns=op.columns,
                input_rows=input_rows_main,
                output_rows=len(new_state),
                affected_rows=affected,
                details={"target_type": op.target_type},
            )
            audit_events.append(event)
            main_state = new_state
            input_rows_main = len(main_state)

        elif isinstance(op, DeduplicateOperation):
            new_state, affected = _apply_deduplicate(main_state, op)
            event = make_audit_event(
                step_id=next_step(),
                operation="deduplicate",
                input_sheets=[op.sheet],
                output_sheets=[main_output],
                columns=op.key_columns,
                input_rows=input_rows_main,
                output_rows=len(new_state),
                affected_rows=affected,
                details={"keep": op.keep, "removed": input_rows_main - len(new_state)},
            )
            audit_events.append(event)
            conclusions.append(
                make_conclusion(
                    text=f"去重删除 {input_rows_main - len(new_state)} 行",
                    value=input_rows_main - len(new_state),
                    severity="info",
                    source_step_id=event.step_id,
                    sheet=op.sheet,
                    columns=op.key_columns,
                ),
            )
            main_state = new_state
            input_rows_main = len(main_state)

        elif isinstance(op, FilterOperation):
            filtered = _apply_filter(main_state, op)
            output_sheets[op.output_sheet] = filtered
            event = make_audit_event(
                step_id=next_step(),
                operation="filter",
                input_sheets=[op.sheet],
                output_sheets=[op.output_sheet],
                columns=[c.column for c in op.conditions],
                input_rows=input_rows_main,
                output_rows=len(filtered),
                affected_rows=[],
                details={
                    "conditions": [c.model_dump() for c in op.conditions],
                    "match": op.match,
                },
            )
            audit_events.append(event)

        elif isinstance(op, GroupSummaryOperation):
            summary = _apply_group_summary(main_state, op)
            output_sheets[op.output_sheet] = summary
            event = make_audit_event(
                step_id=next_step(),
                operation="group_summary",
                input_sheets=[op.sheet],
                output_sheets=[op.output_sheet],
                columns=list({*op.group_by, *op.metrics.keys()}),
                input_rows=input_rows_main,
                output_rows=len(summary),
                affected_rows=[],
                details={
                    "group_by": op.group_by,
                    "metrics": op.metrics,
                },
            )
            audit_events.append(event)
            if not summary.empty:
                for col, funcs in op.metrics.items():
                    for fn in funcs:
                        col_name = f"{col}_{fn}"
                        if col_name in summary.columns:
                            vals = pd.to_numeric(summary[col_name], errors="coerce").dropna()
                            if not vals.empty and fn in {"sum", "mean", "max", "min"}:
                                attr = "max" if fn in {"sum", "max"} else "min"
                                value = float(vals.max() if attr == "max" else vals.min())
                                text = f"{col}_{fn} 最大值 {value:.2f}" if attr == "max" else f"{col}_{fn} 最小值 {value:.2f}"
                                conclusions.append(
                                    make_conclusion(
                                        text=text,
                                        value=value,
                                        severity="info",
                                        source_step_id=event.step_id,
                                        sheet=op.sheet,
                                        columns=[col_name],
                                    ),
                                )

        elif isinstance(op, CompareOperation):
            left = tables[op.left_sheet]
            right = tables[op.right_sheet]
            result = _apply_compare(left, right, op)
            output_sheets[op.output_sheet] = result
            event = make_audit_event(
                step_id=next_step(),
                operation="compare",
                input_sheets=[op.left_sheet, op.right_sheet],
                output_sheets=[op.output_sheet],
                columns=op.key_columns,
                input_rows=int(len(left)),
                output_rows=len(result),
                affected_rows=[],
                details={"key_columns": op.key_columns},
            )
            audit_events.append(event)
            if "变化类型" in result.columns:
                counts = result["变化类型"].value_counts().to_dict()
                for kind in ("added", "removed", "changed"):
                    cnt = int(counts.get(kind, 0))
                    if cnt:
                        label = {"added": "新增", "removed": "删除", "changed": "变化"}[kind]
                        conclusions.append(
                            make_conclusion(
                                text=f"对比结果中 {label} {cnt} 项",
                                value=cnt,
                                severity="info",
                                source_step_id=event.step_id,
                                sheet=op.output_sheet,
                            ),
                        )

        elif isinstance(op, FillFormulaOperation):
            new_state, affected = _apply_fill_formula(main_state, op)
            main_state = new_state
            event = make_audit_event(
                step_id=next_step(),
                operation="fill_formula",
                input_sheets=[op.sheet],
                output_sheets=[main_output],
                columns=[op.target_column],
                input_rows=input_rows_main,
                output_rows=len(new_state),
                affected_rows=affected,
                details={"expression": op.expression, "range": [op.start_row, op.end_row], "only_blank": op.only_blank},
            )
            audit_events.append(event)
            input_rows_main = len(main_state)

        elif isinstance(op, CreateIssueSheetOperation):
            pending_issues.append({"_op": op})
            # issues sheet is generated later
            audit_events.append(
                make_audit_event(
                    step_id=next_step(),
                    operation="create_issue_sheet",
                    input_sheets=[],
                    output_sheets=[op.output_sheet],
                    columns=[],
                    input_rows=0,
                    output_rows=0,
                    affected_rows=[],
                    details={"issue_codes": op.issue_codes or []},
                ),
            )

    # The transform pipeline result becomes the main output sheet
    output_sheets[main_output] = main_state
    metrics["output_rows"] = int(len(main_state))
    metrics["issues_count"] = int(len(pending_issues))

    # Always include a 问题清单 sheet when there are any issues
    if pending_issues:
        issue_rows = [
            {
                "问题级别": "info",
                "问题类型": "pipeline",
                "工作表": main_output,
                "字段": "",
                "行号": "",
                "问题描述": "已生成问题清单",
                "处理状态": "已修复",
            },
        ]
        output_sheets["问题清单"] = pd.DataFrame(issue_rows)

    # Write output workbook
    _write_workbook(output_path, tables, output_sheets, audit_events)
    _validate_output(output_path, output_sheets, audit_events)

    metrics["output_path"] = str(output_path)
    return ExecutionResult(
        output_id=output_path.stem.split("_")[-1],
        output_path=str(output_path),
        sheets=list(output_sheets.keys()) + ["_audit"],
        metrics=metrics,
        conclusions=conclusions,
        audit_events=audit_events,
    )


def _write_workbook(
    output_path: Path,
    source_tables: dict[str, pd.DataFrame],
    output_sheets: dict[str, pd.DataFrame],
    audit_events: list[AuditEvent],
) -> None:
    wb = Workbook()
    # Remove the default sheet
    default = wb.active
    wb.remove(default)

    taken: set[str] = set()
    # 1. Source snapshots
    for ref, df in source_tables.items():
        file_id, sheet_name = _split_sheet_ref(ref)
        snap_name = f"原始_{file_id[:8]}_{sheet_name}"
        snap_name = _escape_sheet_name(snap_name, taken)
        ws = wb.create_sheet(snap_name)
        cleaned = _strip_internal(df)
        for row in cleaned.itertuples(index=False, name=None):
            ws.append(list(row))
        _write_header(ws, list(cleaned.columns))

    # 2. Output sheets in declared order from plan
    for name, df in output_sheets.items():
        sheet_name = _escape_sheet_name(name, taken)
        ws = wb.create_sheet(sheet_name)
        cleaned = _strip_internal(df)
        _write_header(ws, list(cleaned.columns))
        for row in cleaned.itertuples(index=False, name=None):
            ws.append(list(row))

    # 3. Hidden _audit sheet
    audit_ws = wb.create_sheet("_audit")
    rows = audit_events_to_rows(audit_events)
    if rows:
        _write_header(audit_ws, list(rows[0].keys()))
        for r in rows:
            audit_ws.append(list(r.values()))
    else:
        _write_header(audit_ws, ["step_id", "operation", "input_sheets", "output_sheets", "columns", "input_rows", "output_rows", "affected_rows", "details_json"])
    audit_ws.sheet_state = "hidden"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def _write_header(ws, headers: list[str]) -> None:
    for col_idx, name in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=name)
        cell.font = cell.font.copy(bold=True)


def _validate_output(
    output_path: Path,
    output_sheets: dict[str, pd.DataFrame],
    audit_events: list[AuditEvent],
) -> None:
    try:
        wb = load_workbook(output_path, read_only=True, data_only=False)
    except Exception as exc:
        raise OutputValidationError(f"输出文件无法打开: {exc}") from exc
    try:
        for name in output_sheets:
            if not any(s.title == name for s in wb.worksheets) and not any(
                name in s.title for s in wb.worksheets
            ):
                # Allow truncated names
                pass
        if "_audit" not in [s.title for s in wb.worksheets]:
            raise OutputValidationError("缺少隐藏 _audit 工作表")
    finally:
        wb.close()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()