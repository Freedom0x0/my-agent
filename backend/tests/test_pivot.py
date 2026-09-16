"""Tests for tablex_pivot handler and pivot domain."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.app.mcp.handlers import handle_pivot
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session, SessionStore
from backend.app.domain.pivot import crosstab, pivot_table, unpivot


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    store = SessionStore(tmp_path / "out")
    store.output_dir.mkdir(parents=True, exist_ok=True)
    s = store.get_or_create("sess-pivot")
    s.tables["file-A::销售"] = pd.DataFrame({
        "部门": ["研发", "研发", "销售", "销售", "销售"],
        "月份": ["1月", "2月", "1月", "2月", "1月"],
        "金额": [100, 200, 50, 60, 70],
    })
    return s


# ---------- domain ----------


def test_pivot_table_basic() -> None:
    df = pd.DataFrame({
        "dept": ["A", "A", "B", "B"],
        "month": ["Jan", "Feb", "Jan", "Feb"],
        "val": [10, 20, 5, 15],
    })
    out = pivot_table(
        df, index=["dept"], columns=["month"], values=["val"],
        aggfunc="sum", fill_value=0,
    )
    assert len(out) == 2
    assert "month" in out.columns or any("Jan" in str(c) for c in out.columns)


def test_pivot_table_missing_index_column() -> None:
    df = pd.DataFrame({"x": [1]})
    with pytest.raises(ValueError):
        pivot_table(df, index=["y"], columns=["x"], values=["x"])


def test_unpivot_basic() -> None:
    df = pd.DataFrame({
        "id": [1, 2],
        "Jan": [10, 20],
        "Feb": [5, 15],
    })
    out = unpivot(df, index=["id"], var_name="month", value_name="val")
    assert set(out.columns) == {"id", "month", "val"}
    assert len(out) == 4


def test_crosstab_basic() -> None:
    df = pd.DataFrame({
        "row": ["A", "A", "B", "B"],
        "col": ["X", "Y", "X", "Y"],
        "val": [1, 2, 3, 4],
    })
    out = crosstab(df, index=["row"], columns=["col"], fill_value=0)
    assert len(out) == 2


# ---------- handler ----------


def test_handle_pivot_pivot(session: Session) -> None:
    res = handle_pivot(
        ToolCall(
            tool_use_id="p1", name="tablex_pivot",
            input={
                "file_id": "file-A", "sheet": "销售", "operation": "pivot",
                "index": ["部门"], "columns": ["月份"], "values": ["金额"],
                "aggfunc": "sum",
            },
        ),
        session,
    )
    assert res.success
    assert res.data is not None
    assert res.data["rows"] >= 1
    assert "pivot_结果" in session.tables


def test_handle_pivot_unpivot(session: Session) -> None:
    res = handle_pivot(
        ToolCall(
            tool_use_id="p1", name="tablex_pivot",
            input={
                "file_id": "file-A", "sheet": "销售", "operation": "unpivot",
                "index": ["部门"],
            },
        ),
        session,
    )
    assert res.success
    assert res.data["rows"] == 5 * 2


def test_handle_pivot_crosstab(session: Session) -> None:
    res = handle_pivot(
        ToolCall(
            tool_use_id="p1", name="tablex_pivot",
            input={
                "file_id": "file-A", "sheet": "销售", "operation": "crosstab",
                "index": ["部门"], "columns": ["月份"], "aggfunc": "sum",
                "values": ["金额"],
            },
        ),
        session,
    )
    assert res.success


def test_handle_pivot_invalid_operation(session: Session) -> None:
    res = handle_pivot(
        ToolCall(
            tool_use_id="p1", name="tablex_pivot",
            input={
                "file_id": "file-A", "sheet": "销售", "operation": "spin",
            },
        ),
        session,
    )
    assert not res.success


def test_handle_pivot_missing_index(session: Session) -> None:
    res = handle_pivot(
        ToolCall(
            tool_use_id="p1", name="tablex_pivot",
            input={
                "file_id": "file-A", "sheet": "销售", "operation": "pivot",
                "columns": ["月份"],
            },
        ),
        session,
    )
    assert not res.success


def test_handle_pivot_unknown_sheet(session: Session) -> None:
    res = handle_pivot(
        ToolCall(
            tool_use_id="p1", name="tablex_pivot",
            input={
                "file_id": "file-A", "sheet": "nope", "operation": "pivot",
                "index": ["部门"], "columns": ["月份"],
            },
        ),
        session,
    )
    assert not res.success