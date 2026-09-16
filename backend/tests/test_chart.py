"""Tests for tablex_chart handler and chart domain."""
from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd
import pytest

from backend.app.mcp.handlers import handle_chart
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session, SessionStore
from backend.app.domain.chart import (
    ChartError, auto_select_chart, embed_in_excel, generate_chart,
)


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    store = SessionStore(tmp_path / "out")
    store.output_dir.mkdir(parents=True, exist_ok=True)
    s = store.get_or_create("sess-chart")
    s.tables["file-C::销售"] = pd.DataFrame({
        "月份": ["1月", "2月", "3月", "4月", "5月"],
        "营收": [100, 120, 130, 150, 170],
        "成本": [80, 90, 95, 100, 110],
    })
    s.tables["file-C::类别"] = pd.DataFrame({
        "category": ["A", "B", "C", "D", "E"],
        "value": [30, 25, 20, 15, 10],
    })
    return s


# ---------- domain ----------


def test_auto_select_categorical_one_y_returns_pie() -> None:
    df = pd.DataFrame({"c": ["A", "B", "C"], "v": [1, 2, 3]})
    assert auto_select_chart(df, "c", ["v"]) == "pie"


def test_auto_select_categorical_multi_y_returns_bar() -> None:
    df = pd.DataFrame({"c": ["A", "B"], "v1": [1, 2], "v2": [3, 4]})
    assert auto_select_chart(df, "c", ["v1", "v2"]) == "bar"


def test_auto_select_numeric_two_y_returns_scatter() -> None:
    df = pd.DataFrame({
        "x": list(range(50)),
        "v1": [i * 0.5 for i in range(50)],
        "v2": [100 - i for i in range(50)],
    })
    assert auto_select_chart(df, "x", ["v1", "v2"]) == "scatter"


def test_auto_select_datetime_returns_line() -> None:
    df = pd.DataFrame({
        "d": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "v": [1, 2, 3],
    })
    assert auto_select_chart(df, "d", ["v"]) == "line"


def test_generate_chart_bar() -> None:
    df = pd.DataFrame({"x": ["A", "B", "C"], "y": [1, 2, 3]})
    png = generate_chart(df, chart_type="bar", x="x", y=["y"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200


def test_generate_chart_line() -> None:
    df = pd.DataFrame({"x": [1, 2, 3], "y": [1, 2, 3]})
    png = generate_chart(df, chart_type="line", x="x", y=["y"], title="t")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_chart_pie() -> None:
    df = pd.DataFrame({"x": ["A", "B", "C"], "y": [1, 2, 3]})
    png = generate_chart(df, chart_type="pie", x="x", y=["y"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_chart_invalid_type() -> None:
    df = pd.DataFrame({"x": [1], "y": [1]})
    with pytest.raises(ChartError):
        generate_chart(df, chart_type="wat", x="x", y=["y"])


def test_embed_in_excel(tmp_path: Path) -> None:
    xlsx = tmp_path / "test.xlsx"
    from openpyxl import Workbook
    wb = Workbook()
    wb.active["A1"] = "x"
    wb.save(xlsx)
    df = pd.DataFrame({"x": ["A", "B"], "y": [1, 2]})
    png = generate_chart(df, chart_type="bar", x="x", y=["y"])
    embed_in_excel(xlsx, png, sheet_name="图表", cell="A1")
    from openpyxl import load_workbook
    wb2 = load_workbook(xlsx)
    assert "图表" in wb2.sheetnames


# ---------- handler ----------


def test_handle_chart_bar(session: Session) -> None:
    res = handle_chart(
        ToolCall(
            tool_use_id="c1", name="tablex_chart",
            input={
                "file_id": "file-C", "sheet": "销售",
                "chart_type": "bar", "x": "月份", "y": ["营收"],
            },
        ),
        session,
    )
    assert res.success
    assert res.data is not None
    assert "png_base64" in res.data
    base64.b64decode(res.data["png_base64"][:8])


def test_handle_chart_auto_pie(session: Session) -> None:
    res = handle_chart(
        ToolCall(
            tool_use_id="c1", name="tablex_chart",
            input={
                "file_id": "file-C", "sheet": "类别",
                "chart_type": "auto", "x": "category", "y": ["value"],
            },
        ),
        session,
    )
    assert res.success
    assert res.data["chart_type"] == "pie"


def test_handle_chart_auto_line(session: Session) -> None:
    res = handle_chart(
        ToolCall(
            tool_use_id="c1", name="tablex_chart",
            input={
                "file_id": "file-C", "sheet": "销售",
                "chart_type": "auto", "x": "月份", "y": ["营收", "成本"],
            },
        ),
        session,
    )
    assert res.success


def test_handle_chart_unknown_sheet(session: Session) -> None:
    res = handle_chart(
        ToolCall(
            tool_use_id="c1", name="tablex_chart",
            input={
                "file_id": "file-C", "sheet": "nope",
                "chart_type": "bar", "x": "月份", "y": ["营收"],
            },
        ),
        session,
    )
    assert not res.success


def test_handle_chart_empty_y(session: Session) -> None:
    res = handle_chart(
        ToolCall(
            tool_use_id="c1", name="tablex_chart",
            input={
                "file_id": "file-C", "sheet": "销售",
                "chart_type": "bar", "x": "月份", "y": [],
            },
        ),
        session,
    )
    assert not res.success


def test_handle_chart_writes_output_file(session: Session) -> None:
    res = handle_chart(
        ToolCall(
            tool_use_id="c1", name="tablex_chart",
            input={
                "file_id": "file-C", "sheet": "销售",
                "chart_type": "bar", "x": "月份", "y": ["营收"],
            },
        ),
        session,
    )
    assert res.success
    assert res.data is not None
    assert (session.output_dir / f"{res.data['output_id']}.xlsx").exists()