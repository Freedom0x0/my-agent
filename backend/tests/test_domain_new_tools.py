"""Domain-level tests for joiner / pivot / validator / chart edge cases."""
from __future__ import annotations

import pandas as pd
import pytest

from backend.app.domain.joiner import JoinError, join_tables
from backend.app.domain.pivot import pivot_table, unpivot
from backend.app.domain.validator import validate


def test_join_tables_with_nan_keys() -> None:
    left = pd.DataFrame({"id": [1, None, 3], "n": ["a", "b", "c"]})
    right = pd.DataFrame({"id": [1, 3, None], "v": [10, 30, 99]})
    merged, _ = join_tables(left, right, on="id", how="inner")
    # pandas inner join treats NaN==NaN; 3 rows total
    assert len(merged) == 3


def test_join_tables_empty_left() -> None:
    left = pd.DataFrame({"id": [], "n": []})
    right = pd.DataFrame({"id": [1], "v": [10]})
    merged, meta = join_tables(left, right, on="id", how="inner")
    assert len(merged) == 0
    assert meta.left_count == 0


def test_join_tables_duplicate_suffix_columns() -> None:
    left = pd.DataFrame({"id": [1, 2], "v": [10, 20]})
    right = pd.DataFrame({"id": [1, 2], "v": [100, 200]})
    merged, _ = join_tables(left, right, on="id", how="inner", suffix=("_l", "_r"))
    assert "v_l" in merged.columns
    assert "v_r" in merged.columns


def test_join_tables_full() -> None:
    left = pd.DataFrame({"id": [1, 2]})
    right = pd.DataFrame({"id": [2, 3]})
    merged, meta = join_tables(left, right, on="id", how="full")
    assert len(merged) == 3


def test_pivot_table_agg_conflict() -> None:
    df = pd.DataFrame({
        "row": ["A", "A", "B", "B"],
        "col": ["X", "Y", "X", "Y"],
        "v": [1, 2, 3, 4],
    })
    out = pivot_table(df, index=["row"], columns=["col"], values=["v"], aggfunc="sum")
    # columns were flattened: v_X / v_Y
    assert int(out["v_X"].sum()) == 4


def test_pivot_table_with_nan_fill() -> None:
    df = pd.DataFrame({
        "row": ["A", "A", "B"],
        "col": ["X", "Y", "X"],
        "v": [1, 2, 3],
    })
    out = pivot_table(df, index=["row"], columns=["col"], values=["v"], fill_value=-1)
    found = -1 in out.values.flatten()
    assert found


def test_unpivot_preserves_row_count() -> None:
    df = pd.DataFrame({"id": [1, 2], "a": [10, 20], "b": [5, 15]})
    out = unpivot(df, index=["id"])
    assert len(out) == 4


def test_validate_range_date_column() -> None:
    df = pd.DataFrame({"d": ["2024-01-01", "2030-01-01", "not-a-date"]})
    results = validate(df, [{"column": "d", "type": "format", "pattern": r"^\d{4}-\d{2}-\d{2}$"}])
    assert results[0].failed == 1


def test_validate_not_null_with_whitespace() -> None:
    df = pd.DataFrame({"a": ["x", "   ", "y"]})
    results = validate(df, [{"column": "a", "type": "not_null"}])
    assert results[0].failed == 1