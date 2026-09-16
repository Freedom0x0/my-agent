"""Data-quality issue detection helpers."""
from __future__ import annotations

from typing import Any

import pandas as pd

from ._transform import coerce_date, coerce_numeric

MAX_AFFECTED_ROWS_LOG = 200
_DATE_PROBE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
)


def count_nulls(series: pd.Series) -> int:
    mask = series.isna()
    text_mask = series.astype(str).str.strip().isin(["", "nan", "None"])
    return int((mask | text_mask).sum())


def detect_mixed_numeric(series: pd.Series) -> tuple[bool, list[int]]:
    rows: list[int] = []
    seen_numeric = False
    seen_text = False
    for idx, value in enumerate(series.tolist()):
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if coerce_numeric(value) is not None:
            seen_numeric = True
        else:
            seen_text = True
            rows.append(idx + 1)
        if seen_numeric and seen_text:
            return True, rows[:MAX_AFFECTED_ROWS_LOG]
    return False, []


def detect_mixed_date(series: pd.Series) -> tuple[bool, list[int]]:
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


def detect_duplicates(df: pd.DataFrame) -> tuple[bool, list[int]]:
    if df.empty:
        return False, []
    dup_mask = df.duplicated(keep="first")
    if not dup_mask.any():
        return False, []
    rows = df.index[dup_mask].tolist()
    return True, [r + 1 for r in rows[:MAX_AFFECTED_ROWS_LOG]]
