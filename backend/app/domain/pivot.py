"""Pivot / unpivot / crosstab business logic for tablex_pivot."""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd


AggFunc = Literal["sum", "mean", "count", "min", "max"]


def pivot_table(
    df: pd.DataFrame,
    *,
    index: list[str],
    columns: list[str],
    values: list[str] | None = None,
    aggfunc: AggFunc = "sum",
    fill_value: float | None = 0,
) -> pd.DataFrame:
    for col in index:
        if col not in df.columns:
            raise ValueError(f"缺少列: {col}")
    for col in columns:
        if col not in df.columns:
            raise ValueError(f"缺少列: {col}")
    if values:
        for col in values:
            if col not in df.columns:
                raise ValueError(f"缺少列: {col}")
    kwargs: dict[str, Any] = {
        "index": index,
        "columns": columns,
        "aggfunc": aggfunc,
    }
    if values:
        kwargs["values"] = values
    if fill_value is not None:
        kwargs["fill_value"] = fill_value
    result = df.pivot_table(**kwargs)
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = ["_".join(str(c) for c in col).strip("_") for col in result.columns]
    return result.reset_index()


def unpivot(
    df: pd.DataFrame,
    *,
    index: list[str],
    var_name: str = "variable",
    value_name: str = "value",
) -> pd.DataFrame:
    for col in index:
        if col not in df.columns:
            raise ValueError(f"缺少列: {col}")
    return df.melt(id_vars=index, var_name=var_name, value_name=value_name)


def crosstab(
    df: pd.DataFrame,
    *,
    index: list[str],
    columns: list[str],
    values: list[str] | None = None,
    aggfunc: AggFunc | None = None,
    fill_value: float = 0,
) -> pd.DataFrame:
    for col in index:
        if col not in df.columns:
            raise ValueError(f"缺少列: {col}")
    for col in columns:
        if col not in df.columns:
            raise ValueError(f"缺少列: {col}")
    if len(index) != 1 or len(columns) != 1:
        raise ValueError("crosstab 仅支持单列 index 和 columns")

    kwargs: dict[str, Any] = {
        "index": df[index[0]],
        "columns": df[columns[0]],
        "normalize": False,
        "margins": False,
    }
    if values:
        if aggfunc is None:
            raise ValueError("crosstab 配合 values 时必须提供 aggfunc")
        kwargs["values"] = df[values[0]]
        kwargs["aggfunc"] = aggfunc
    result = pd.crosstab(**kwargs)
    return result.fillna(fill_value).reset_index()