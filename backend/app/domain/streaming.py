"""Chunked reading for large workbooks.

ponytail: pandas .iloc is already O(1) per row slice; no streaming IO needed
for xlsx/csv because pandas materialises everything. Upgrade path: use
openpyxl read_only=True + manual header detection for files > 1M rows.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd


def read_chunk(
    df: pd.DataFrame,
    *,
    offset: int = 0,
    limit: int = 1000,
    columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Slice a DataFrame by offset/limit; optionally project to a column subset."""
    if offset < 0:
        raise ValueError("offset 必须为非负整数")
    if limit < 0:
        raise ValueError("limit 必须为非负整数")

    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise KeyError(f"列不存在: {missing}")
        df = df[list(columns)]

    end = offset + limit
    return df.iloc[offset:end].copy()


def total_rows(df: pd.DataFrame) -> int:
    return len(df)
