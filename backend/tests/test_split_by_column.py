"""Tests for tablex_split_by_column handler."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.app.mcp.handlers import handle_split_by_column
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    s = Session("s", tmp_path / "out")
    s.files["file-S"] = {"path": "x", "sha256": "x", "original_name": "s.xlsx"}
    s.tables["file-S::明细"] = pd.DataFrame({
        "部门": ["研发", "销售", "研发", "销售", "研发", "运营"],
        "金额": [100, 200, 300, 400, 500, 600],
    })
    return s


def test_split_by_column_happy(session: Session) -> None:
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp1", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "明细", "group_column": "部门", "output_name": "按部门拆分"},
        ),
        session,
    )
    assert res.success
    assert res.data["output_name"] == "按部门拆分"
    assert "output_id" not in res.data
    assert set(res.data["sheets"]) == {"研发", "销售", "运营"}
    assert len(session.tables["研发"]) == 3
    assert len(session.tables["销售"]) == 2
    assert len(session.tables["运营"]) == 1


def test_split_by_column_skips_null_values(session: Session) -> None:
    session.tables["file-S::明细"] = pd.DataFrame({
        "部门": ["研发", None, "销售", "销售"],
        "金额": [1, 2, 3, 4],
    })
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp2", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "明细", "group_column": "部门", "output_name": "拆分"},
        ),
        session,
    )
    assert res.success
    assert set(res.data["sheets"]) == {"研发", "销售"}


def test_split_by_column_unknown_column(session: Session) -> None:
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp3", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "明细", "group_column": "nope", "output_name": "x"},
        ),
        session,
    )
    assert not res.success
    assert "不存在" in (res.error or "")


def test_split_by_column_all_null(session: Session) -> None:
    session.tables["file-S::明细"] = pd.DataFrame({"部门": [None, None], "金额": [1, 2]})
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp4", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "明细", "group_column": "部门", "output_name": "x"},
        ),
        session,
    )
    assert not res.success


def test_split_by_column_requires_output_name(session: Session) -> None:
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp5", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "明细", "group_column": "部门"},
        ),
        session,
    )
    assert not res.success
    assert "output_name" in (res.error or "")


def test_split_by_column_unknown_sheet(session: Session) -> None:
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp6", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "nope", "group_column": "部门", "output_name": "x"},
        ),
        session,
    )
    assert not res.success


def test_split_by_column_truncates_long_sheet_name(session: Session) -> None:
    session.tables["file-S::明细"] = pd.DataFrame({
        "部门": ["a" * 60],  # longer than 31 chars
        "金额": [1],
    })
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp7", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "明细", "group_column": "部门", "output_name": "long"},
        ),
        session,
    )
    assert res.success
    assert all(len(name) <= 31 for name in res.data["sheets"])


def test_split_by_column_avoid_name_collision(session: Session) -> None:
    session.tables["file-S::明细"] = pd.DataFrame({
        "部门": ["研发", "研发_2", "研发"],
        "金额": [1, 2, 3],
    })
    session.tables["研发"] = pd.DataFrame({"x": [0]})  # pre-existing
    res = handle_split_by_column(
        ToolCall(
            tool_use_id="sp8", name="tablex_split_by_column",
            input={"file_id": "file-S", "sheet": "明细", "group_column": "部门", "output_name": "split"},
        ),
        session,
    )
    assert res.success
    assert len(set(res.data["sheets"])) == len(res.data["sheets"])