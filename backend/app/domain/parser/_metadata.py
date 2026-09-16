"""Column metadata helpers: header detection, name normalization, DataFrame build."""
from __future__ import annotations

from typing import Any

import pandas as pd

from ...schemas import ColumnInspection, DataIssue

RESERVED_PREFIX = "__tablex_"
INTERNAL_SOURCE_ROW = "__tablex_source_row__"
INTERNAL_COL = INTERNAL_SOURCE_ROW
MAX_PREVIEW_ROWS = 20
HEADER_SCAN_LIMIT = 20


def detect_header_row(raw_rows: list[list[Any]]) -> int:
    for idx, row in enumerate(raw_rows[:HEADER_SCAN_LIMIT]):
        non_empty = sum(1 for cell in row if cell is not None and str(cell).strip() != "")
        if non_empty >= 2:
            return idx
    return -1


def normalize_header(value: Any, used: set[str], issues: list[DataIssue], sheet_name: str) -> str:
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


def build_dataframe(raw_rows: list[list[Any]], header_idx: int, columns: list[str]) -> pd.DataFrame:
    data = raw_rows[header_idx + 1:]
    rows: list[dict[str, Any]] = []
    for r in data:
        record = {col: (r[i] if i < len(r) else None) for i, col in enumerate(columns)}
        rows.append(record)
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows, columns=columns)
    return df
