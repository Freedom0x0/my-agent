"""Workbook parsing and table-health inspection."""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook as openpyxl_load

from ..schemas import ColumnInspection, DataIssue, SheetInspection, WorkbookInspection

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
RESERVED_PREFIX = "__tablex_"
INTERNAL_SOURCE_ROW = "__tablex_source_row__"
MAX_PREVIEW_ROWS = 20
HEADER_SCAN_LIMIT = 20
MAX_AFFECTED_ROWS_LOG = 200

XLSX_SIGNATURE = b"PK"
XLS_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%Y年%m月%d日%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
)

_NUMERIC_CLEAN = re.compile(r"[,\s¥$￥€£%元万元]")
_DATE_PROBE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
)


class UnsupportedFileError(ValueError):
    """Raised when the file extension or magic bytes are not supported."""


def _detect_extension(path: Path) -> str:
    return path.suffix.lower()


def _verify_magic(path: Path, ext: str) -> None:
    """Verify file header matches the declared extension."""
    raw = path.read_bytes()
    head = raw[:8]
    if ext == ".xlsx":
        if not head.startswith(XLSX_SIGNATURE):
            raise UnsupportedFileError("文件不是有效的 xlsx 格式")
    elif ext == ".xls":
        if not head.startswith(XLS_SIGNATURE):
            raise UnsupportedFileError("文件不是有效的 xls 格式")
    elif ext == ".csv":
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                raw.decode(encoding)
                return
            except UnicodeDecodeError:
                continue
        raise UnsupportedFileError("csv 文件编码无法识别，请使用 UTF-8 或 GB18030")


def _read_csv_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            raw.decode(encoding)
            return raw
        except UnicodeDecodeError:
            continue
    raise UnsupportedFileError("csv 文件编码无法识别，请使用 UTF-8 或 GB18030")


def _sniff_delimiter(text: str) -> str:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        return dialect.delimiter
    except csv.Error:
        return ","


def _detect_header_row(raw_rows: list[list[Any]]) -> int:
    for idx, row in enumerate(raw_rows[:HEADER_SCAN_LIMIT]):
        non_empty = sum(1 for cell in row if cell is not None and str(cell).strip() != "")
        if non_empty >= 2:
            return idx
    return -1


def _normalize_header(value: Any, used: set[str], issues: list[DataIssue], sheet_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        text = "未命名列"
    base = text
    n = 1
    while text in used:
        n += 1
        text = f"{base}_{n}"
    if text != base:
        issues.append(
            DataIssue(
                code="blank_header" if base.startswith("未命名列") else "blank_header",
                severity="warning",
                message=f"表头为空或重复，已重命名为 {text}",
                sheet=sheet_name,
                column=text,
            ),
        )
    used.add(text)
    return text


def _coerce_numeric(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = _NUMERIC_CLEAN.sub("", text)
    if cleaned == "" or cleaned in {"-", "+", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _coerce_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    # Try direct formats first
    for fmt in DATE_FORMATS:
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


def _infer_column_type(series: pd.Series) -> tuple[str, int, int, list[str]]:
    non_null = series.dropna()
    non_null = non_null[non_null.astype(str).str.strip() != ""]
    if len(non_null) == 0:
        return "empty", 0, 0, []
    # boolean probe
    bool_set = {"true", "false", "TRUE", "FALSE", "True", "False", "是", "否", "yes", "no"}
    if all(str(v).strip() in bool_set for v in non_null):
        return "boolean", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    # date probe
    date_hits = sum(1 for v in non_null if _coerce_date(v) is not None)
    if date_hits == len(non_null):
        return "date", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    # number probe
    num_hits = sum(1 for v in non_null if _coerce_numeric(v) is not None)
    if num_hits == len(non_null):
        return "number", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    if num_hits > 0:
        return "mixed", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    return "text", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]


def _count_nulls(series: pd.Series) -> int:
    mask = series.isna()
    text_mask = series.astype(str).str.strip().isin(["", "nan", "None"])
    return int((mask | text_mask).sum())


def _detect_mixed_numeric(series: pd.Series) -> tuple[bool, list[int]]:
    rows: list[int] = []
    seen_numeric = False
    seen_text = False
    for idx, value in enumerate(series.tolist()):
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if _coerce_numeric(value) is not None:
            seen_numeric = True
        else:
            seen_text = True
            rows.append(idx + 1)
        if seen_numeric and seen_text:
            return True, rows[:MAX_AFFECTED_ROWS_LOG]
    return False, []


def _detect_mixed_date(series: pd.Series) -> tuple[bool, list[int]]:
    rows: list[int] = []
    seen = False
    formats_seen: set[str] = set()
    for idx, value in enumerate(series.tolist()):
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        text = str(value).strip()
        matched_fmt: str | None = None
        for fmt in _DATE_PROBE_FORMATS:
            try:
                pd.to_datetime(text, format=fmt, errors="raise")
                matched_fmt = fmt
                break
            except (ValueError, TypeError):
                continue
        if matched_fmt is None:
            try:
                pd.to_datetime(text, errors="raise")
                matched_fmt = "iso"
            except (ValueError, TypeError, pd.errors.ParserError):
                continue
        if matched_fmt is not None:
            formats_seen.add(matched_fmt)
            if len(formats_seen) >= 2:
                seen = True
                rows.append(idx + 1)
    return seen, rows[:MAX_AFFECTED_ROWS_LOG]


def _detect_duplicates(df: pd.DataFrame) -> tuple[bool, list[int]]:
    if df.empty:
        return False, []
    dup_mask = df.duplicated(keep="first")
    if not dup_mask.any():
        return False, []
    rows = df.index[dup_mask].tolist()
    return True, [r + 1 for r in rows[:MAX_AFFECTED_ROWS_LOG]]


def _build_dataframe(raw_rows: list[list[Any]], header_idx: int, columns: list[str]) -> pd.DataFrame:
    data = raw_rows[header_idx + 1:]
    rows: list[dict[str, Any]] = []
    for r in data:
        record = {col: (r[i] if i < len(r) else None) for i, col in enumerate(columns)}
        rows.append(record)
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows, columns=columns)
    return df


def _sheet_from_xlsx(path: Path, sheet_name: str) -> tuple[SheetInspection, pd.DataFrame]:
    wb = openpyxl_load(path, read_only=True, data_only=False)
    try:
        ws = wb[sheet_name]
        raw_rows: list[list[Any]] = []
        for row in ws.iter_rows(values_only=True):
            raw_rows.append(list(row))
    finally:
        wb.close()
    issues: list[DataIssue] = []
    header_idx = _detect_header_row(raw_rows)
    if header_idx < 0:
        issues.append(
            DataIssue(
                code="empty_sheet",
                severity="warning",
                message="未在 20 行内找到表头",
                sheet=sheet_name,
            ),
        )
        return SheetInspection(
            name=sheet_name,
            row_count=0,
            column_count=0,
            columns=[],
            issues=issues,
        ), pd.DataFrame()

    used_names: set[str] = set()
    raw_header = raw_rows[header_idx]
    columns = [_normalize_header(cell, used_names, issues, sheet_name) for cell in raw_header]

    # Drop fully empty rows below the header
    body = [r for r in raw_rows[header_idx + 1:] if any(c is not None and str(c).strip() != "" for c in r)]

    df = pd.DataFrame(body, columns=columns)
    df = df.astype(object).where(df.notna(), None)
    df.columns = columns

    # Drop columns that are completely empty
    keep = [c for c in columns if (df[c].notna() & (df[c].astype(str).str.strip() != "")).any()]
    df = df[keep]
    columns = keep

    formula_count = 0
    # detect formulas via second open of workbook
    wb2 = openpyxl_load(path, read_only=True, data_only=False)
    try:
        ws2 = wb2[sheet_name]
        for row in ws2.iter_rows(values_only=False):
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v.startswith("="):
                    formula_count += 1
    finally:
        wb2.close()

    col_inspections: list[ColumnInspection] = []
    for col in columns:
        null_count = _count_nulls(df[col]) if not df.empty else 0
        unique_count = int(df[col].dropna().astype(str).str.strip().nunique()) if not df.empty else 0
        inferred_type, _, _, samples = _infer_column_type(df[col]) if not df.empty else ("empty", 0, 0, [])
        col_inspections.append(
            ColumnInspection(
                name=col,
                inferred_type=inferred_type,
                null_count=null_count,
                unique_count=unique_count,
                sample_values=samples,
            ),
        )
        if col.startswith(RESERVED_PREFIX):
            issues.append(
                DataIssue(
                    code="reserved_column",
                    severity="error",
                    message=f"列名 {col} 使用了系统保留前缀",
                    sheet=sheet_name,
                    column=col,
                ),
            )
        if null_count > 0:
            null_rows = [i + 1 for i, v in enumerate(df[col].tolist()) if v is None or str(v).strip() == ""]
            issues.append(
                DataIssue(
                    code="null_values",
                    severity="warning",
                    message=f"列 {col} 存在 {null_count} 个空值",
                    sheet=sheet_name,
                    column=col,
                    rows=null_rows[:MAX_AFFECTED_ROWS_LOG],
                ),
            )
        if inferred_type == "mixed":
            mixed, mixed_rows = _detect_mixed_numeric(df[col])
            if mixed:
                issues.append(
                    DataIssue(
                        code="mixed_numeric",
                        severity="warning",
                        message=f"列 {col} 同时包含数字和文本",
                        sheet=sheet_name,
                        column=col,
                        rows=mixed_rows,
                    ),
                )
        # mixed date detection on text-looking date columns
        mixed_date, rows_md = _detect_mixed_date(df[col]) if not df.empty else (False, [])
        if mixed_date:
            _, _, rows_md = _detect_mixed_date(df[col])
            issues.append(
                DataIssue(
                    code="mixed_date",
                    severity="warning",
                    message=f"列 {col} 存在多种日期格式",
                    sheet=sheet_name,
                    column=col,
                    rows=rows_md,
                ),
            )

    if not df.empty:
        dup, dup_rows = _detect_duplicates(df)
        if dup:
            issues.append(
                DataIssue(
                    code="duplicate_rows",
                    severity="warning",
                    message=f"检测到 {len(dup_rows)} 行重复",
                    sheet=sheet_name,
                    rows=dup_rows,
                ),
            )

    preview_records = df.head(MAX_PREVIEW_ROWS).to_dict(orient="records") if not df.empty else []

    sheet = SheetInspection(
        name=sheet_name,
        row_count=len(df),
        column_count=len(columns),
        columns=col_inspections,
        preview=preview_records,
        issues=issues,
        formula_count=formula_count,
    )
    df_with_row = df.copy()
    df_with_row[INTERNAL_SOURCE_ROW] = list(range(header_idx + 2, header_idx + 2 + len(df)))
    return sheet, df_with_row


def _sheet_from_csv(path: Path) -> tuple[SheetInspection, pd.DataFrame]:
    raw = _read_csv_bytes(path)
    text = raw.decode("utf-8-sig", errors="replace")
    if text.startswith("﻿"):
        text = text[1:]
    delimiter = _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    raw_rows = [row for row in reader]
    issues: list[DataIssue] = []
    header_idx = _detect_header_row(raw_rows)
    if header_idx < 0:
        issues.append(
            DataIssue(
                code="empty_sheet",
                severity="warning",
                message="未在 20 行内找到表头",
                sheet="数据",
            ),
        )
        return SheetInspection(
            name="数据",
            row_count=0,
            column_count=0,
            columns=[],
            issues=issues,
        ), pd.DataFrame()

    used: set[str] = set()
    columns = [_normalize_header(cell, used, issues, "数据") for cell in raw_rows[header_idx]]
    body = [r for r in raw_rows[header_idx + 1:] if any(c is not None and str(c).strip() != "" for c in r)]
    df = pd.DataFrame(body, columns=columns)
    df = df.astype(object).where(df.notna(), None)
    keep = [c for c in columns if (df[c].notna() & (df[c].astype(str).str.strip() != "")).any()]
    df = df[keep]
    columns = keep

    col_inspections: list[ColumnInspection] = []
    for col in columns:
        null_count = _count_nulls(df[col]) if not df.empty else 0
        unique_count = int(df[col].dropna().astype(str).str.strip().nunique()) if not df.empty else 0
        inferred_type, _, _, samples = _infer_column_type(df[col]) if not df.empty else ("empty", 0, 0, [])
        col_inspections.append(
            ColumnInspection(
                name=col,
                inferred_type=inferred_type,
                null_count=null_count,
                unique_count=unique_count,
                sample_values=samples,
            ),
        )
        if col.startswith(RESERVED_PREFIX):
            issues.append(
                DataIssue(
                    code="reserved_column",
                    severity="error",
                    message=f"列名 {col} 使用了系统保留前缀",
                    sheet="数据",
                    column=col,
                ),
            )
        if null_count > 0:
            null_rows = [i + 1 for i, v in enumerate(df[col].tolist()) if v is None or str(v).strip() == ""]
            issues.append(
                DataIssue(
                    code="null_values",
                    severity="warning",
                    message=f"列 {col} 存在 {null_count} 个空值",
                    sheet="数据",
                    column=col,
                    rows=null_rows[:MAX_AFFECTED_ROWS_LOG],
                ),
            )
        if inferred_type == "mixed":
            mixed, mixed_rows = _detect_mixed_numeric(df[col])
            if mixed:
                issues.append(
                    DataIssue(
                        code="mixed_numeric",
                        severity="warning",
                        message=f"列 {col} 同时包含数字和文本",
                        sheet="数据",
                        column=col,
                        rows=mixed_rows,
                    ),
                )

    if not df.empty:
        dup, dup_rows = _detect_duplicates(df)
        if dup:
            issues.append(
                DataIssue(
                    code="duplicate_rows",
                    severity="warning",
                    message=f"检测到 {len(dup_rows)} 行重复",
                    sheet="数据",
                    rows=dup_rows,
                ),
            )

    preview_records = df.head(MAX_PREVIEW_ROWS).to_dict(orient="records") if not df.empty else []
    sheet = SheetInspection(
        name="数据",
        row_count=len(df),
        column_count=len(columns),
        columns=col_inspections,
        preview=preview_records,
        issues=issues,
    )
    df_with_row = df.copy()
    df_with_row[INTERNAL_SOURCE_ROW] = list(range(header_idx + 2, header_idx + 2 + len(df)))
    return sheet, df_with_row


def _sheet_from_xls(path: Path) -> tuple[SheetInspection, pd.DataFrame]:
    xls = pd.ExcelFile(path, engine="xlrd")
    if not xls.sheet_names:
        return SheetInspection(
            name="Sheet1",
            row_count=0,
            column_count=0,
            columns=[],
            issues=[
                DataIssue(
                    code="empty_sheet",
                    severity="warning",
                    message="xls 工作簿没有可用工作表",
                    sheet="Sheet1",
                ),
            ],
        ), pd.DataFrame()
    sheet_name = xls.sheet_names[0]
    df = xls.parse(sheet_name=sheet_name, header=None)
    raw_rows: list[list[Any]] = df.astype(object).where(df.notna(), None).values.tolist()
    issues: list[DataIssue] = []
    header_idx = _detect_header_row(raw_rows)
    if header_idx < 0:
        issues.append(
            DataIssue(
                code="empty_sheet",
                severity="warning",
                message="未在 20 行内找到表头",
                sheet=sheet_name,
            ),
        )
        return SheetInspection(
            name=sheet_name,
            row_count=0,
            column_count=0,
            columns=[],
            issues=issues,
        ), pd.DataFrame()
    used: set[str] = set()
    columns = [_normalize_header(cell, used, issues, sheet_name) for cell in raw_rows[header_idx]]
    body = raw_rows[header_idx + 1:]
    df = pd.DataFrame(body, columns=columns).astype(object).where(
        pd.DataFrame(body, columns=columns).notna(), None,
    )
    keep = [c for c in columns if (df[c].notna() & (df[c].astype(str).str.strip() != "")).any()]
    df = df[keep]
    columns = keep
    col_inspections: list[ColumnInspection] = []
    for col in columns:
        null_count = _count_nulls(df[col]) if not df.empty else 0
        unique_count = int(df[col].dropna().astype(str).str.strip().nunique()) if not df.empty else 0
        inferred_type, _, _, samples = _infer_column_type(df[col]) if not df.empty else ("empty", 0, 0, [])
        col_inspections.append(
            ColumnInspection(
                name=col,
                inferred_type=inferred_type,
                null_count=null_count,
                unique_count=unique_count,
                sample_values=samples,
            ),
        )
    preview_records = df.head(MAX_PREVIEW_ROWS).to_dict(orient="records") if not df.empty else []
    sheet = SheetInspection(
        name=sheet_name,
        row_count=len(df),
        column_count=len(columns),
        columns=col_inspections,
        preview=preview_records,
        issues=issues,
        formula_count=0,
    )
    df_with_row = df.copy()
    df_with_row[INTERNAL_SOURCE_ROW] = list(range(header_idx + 2, header_idx + 2 + len(df)))
    return sheet, df_with_row


def inspect_workbook(path: Path) -> WorkbookInspection:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    ext = _detect_extension(path)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"不支持的扩展名 {ext}")
    _verify_magic(path, ext)

    if ext == ".xlsx":
        wb = openpyxl_load(path, read_only=True, data_only=False)
        try:
            sheet_names = wb.sheetnames
        finally:
            wb.close()
        inspections: list[SheetInspection] = []
        for name in sheet_names:
            sheet, _ = _sheet_from_xlsx(path, name)
            inspections.append(sheet)
        return WorkbookInspection(filename=path.name, file_type="xlsx", sheets=inspections)
    if ext == ".csv":
        sheet, _ = _sheet_from_csv(path)
        return WorkbookInspection(filename=path.name, file_type="csv", sheets=[sheet])
    sheet, _ = _sheet_from_xls(path)
    return WorkbookInspection(filename=path.name, file_type="xls", sheets=[sheet])


def load_tables(path: Path) -> dict[str, pd.DataFrame]:
    """Load normalized tables with internal source-row column."""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    ext = _detect_extension(path)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"不支持的扩展名 {ext}")
    _verify_magic(path, ext)

    if ext == ".xlsx":
        wb = openpyxl_load(path, read_only=True, data_only=False)
        try:
            sheet_names = wb.sheetnames
        finally:
            wb.close()
        tables: dict[str, pd.DataFrame] = {}
        for name in sheet_names:
            _, df = _sheet_from_xlsx(path, name)
            tables[name] = df.reset_index(drop=True)
        return tables
    if ext == ".csv":
        _, df = _sheet_from_csv(path)
        return {"数据": df.reset_index(drop=True)}
    _, df = _sheet_from_xls(path)
    return {df.attrs.get("sheet_name", "Sheet1"): df.reset_index(drop=True)}


def is_supported_file(path: Path) -> bool:
    return _detect_extension(path) in SUPPORTED_EXTENSIONS