"""Type inference and value coercion utilities."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

_NUMERIC_CLEAN = re.compile(r"[,\s¥$￥€£%元万元]")
_DATE_PROBE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
)

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%Y年%m月%d日%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
)


def coerce_numeric(value: Any) -> float | None:
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


def coerce_date(value: Any) -> str | None:
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


def infer_column_type(series: pd.Series) -> tuple[str, int, int, list[str]]:
    non_null = series.dropna()
    non_null = non_null[non_null.astype(str).str.strip() != ""]
    if len(non_null) == 0:
        return "empty", 0, 0, []
    # boolean probe
    bool_set = {"true", "false", "TRUE", "FALSE", "True", "False", "是", "否", "yes", "no"}
    if all(str(v).strip() in bool_set for v in non_null):
        return "boolean", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    # date probe
    date_hits = sum(1 for v in non_null if coerce_date(v) is not None)
    if date_hits == len(non_null):
        return "date", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    # number probe
    num_hits = sum(1 for v in non_null if coerce_numeric(v) is not None)
    if num_hits == len(non_null):
        return "number", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    if num_hits > 0:
        return "mixed", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
    return "text", 0, non_null.nunique(), [str(v) for v in non_null.head(5)]
