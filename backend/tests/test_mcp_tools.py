"""Unit tests for each tablex_* handler (success and failure paths)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from backend.app.db import FileRecord, init_db, insert_file
from backend.app.mcp.handlers import (
    HANDLERS,
    handle_compare,
    handle_deduplicate,
    handle_export,
    handle_fill_formula,
    handle_fill_null,
    handle_filter,
    handle_group_summary,
    handle_inspect,
    handle_normalize,
    handle_sort,
    handle_upload,
    truncate_result,
    validate_tool_input,
)
from backend.app.mcp.schemas import MAX_RESULT_BYTES, ToolCall, ToolResult
from backend.app.mcp.session import Session, SessionStore


@pytest.fixture()
def sample_workbook(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["部门", "订单号", "金额"])
    ws.append(["研发", "A001", "1,200"])
    ws.append(["销售", "A002", "800"])
    ws.append(["研发", "A001", "1,200"])  # duplicate
    ws.append(["销售", None, "1,500"])
    out = tmp_path / "sample.xlsx"
    wb.save(out)
    return out


@pytest.fixture()
def session(sample_workbook: Path) -> Session:
    store = SessionStore(tmp_dir := sample_workbook.parent / "outputs")
    store.output_dir.mkdir(parents=True, exist_ok=True)
    s = store.get_or_create("sess-test")
    s.files["file-001"] = {
        "path": str(sample_workbook),
        "sha256": "x",
        "original_name": "sample.xlsx",
    }
    # Pre-load tables as if tablex_upload had been called.
    from backend.app.domain.parser import load_tables

    for name, df in load_tables(sample_workbook).items():
        s.tables[f"file-001::{name}"] = df
    return s


def test_all_tools_have_handlers() -> None:
    assert set(HANDLERS.keys()) == {
        "tablex_chart",
        "tablex_compare",
        "tablex_deduplicate",
        "tablex_export",
        "tablex_fill_formula",
        "tablex_fill_null",
        "tablex_filter",
        "tablex_group_summary",
        "tablex_inspect",
        "tablex_join",
        "tablex_normalize",
        "tablex_pivot",
        "tablex_sort",
        "tablex_upload",
        "tablex_validate",
    }


# ---------- validate_tool_input ----------


def test_validate_unknown_tool(session: Session) -> None:
    res = validate_tool_input("tablex_nope", {}, session)
    assert not res.ok
    assert "未知工具" in (res.error or "")


def test_validate_missing_required_field(session: Session) -> None:
    res = validate_tool_input("tablex_normalize", {"file_id": "file-001"}, session)
    assert not res.ok
    assert "缺少参数" in (res.error or "")


def test_validate_unknown_file(session: Session) -> None:
    res = validate_tool_input(
        "tablex_normalize",
        {"file_id": "missing", "sheet": "明细", "columns": ["金额"], "target_type": "number"},
        session,
    )
    assert not res.ok
    assert "文件不存在" in (res.error or "")


def test_validate_sheet_not_loaded(session: Session) -> None:
    res = validate_tool_input(
        "tablex_normalize",
        {"file_id": "file-001", "sheet": "不存在的", "columns": ["金额"], "target_type": "number"},
        session,
    )
    assert not res.ok
    assert "工作表未加载" in (res.error or "")


def test_validate_ok(session: Session) -> None:
    res = validate_tool_input(
        "tablex_normalize",
        {"file_id": "file-001", "sheet": "明细", "columns": ["金额"], "target_type": "number"},
        session,
    )
    assert res.ok


# ---------- handle_upload ----------


def test_handle_upload_loads_sheets(sample_workbook: Path, tmp_path: Path) -> None:
    s = Session("s", tmp_path / "out")
    s.files["file-001"] = {"path": str(sample_workbook), "sha256": "x", "original_name": "sample.xlsx"}
    res = handle_upload(ToolCall(tool_use_id="u1", name="tablex_upload", input={"file_id": "file-001"}), s)
    assert res.success
    assert "file-001::明细" in s.tables


def test_handle_upload_missing_file(tmp_path: Path) -> None:
    s = Session("s", tmp_path / "out")
    s.files["file-001"] = {"path": str(tmp_path / "ghost.xlsx"), "sha256": "x", "original_name": "ghost"}
    res = handle_upload(ToolCall(tool_use_id="u1", name="tablex_upload", input={"file_id": "file-001"}), s)
    assert not res.success


# ---------- handle_inspect ----------


def test_handle_inspect_returns_summary(session: Session) -> None:
    res = handle_inspect(ToolCall(tool_use_id="i1", name="tablex_inspect", input={"file_id": "file-001"}), session)
    assert res.success
    assert res.data is not None
    assert res.data["row_count"] >= 3


def test_handle_inspect_unknown_sheet(session: Session) -> None:
    res = handle_inspect(
        ToolCall(tool_use_id="i1", name="tablex_inspect", input={"file_id": "file-001", "sheet": "Nope"}),
        session,
    )
    assert not res.success


# ---------- handle_normalize ----------


def test_handle_normalize_success(session: Session) -> None:
    res = handle_normalize(
        ToolCall(
            tool_use_id="n1",
            name="tablex_normalize",
            input={"file_id": "file-001", "sheet": "明细", "columns": ["金额"], "target_type": "number"},
        ),
        session,
    )
    assert res.success
    assert any(a.operation == "normalize" for a in session.audit_events)


def test_handle_normalize_unknown_column(session: Session) -> None:
    res = handle_normalize(
        ToolCall(
            tool_use_id="n1",
            name="tablex_normalize",
            input={"file_id": "file-001", "sheet": "明细", "columns": ["不存在的列"], "target_type": "number"},
        ),
        session,
    )
    assert not res.success


# ---------- handle_deduplicate ----------


def test_handle_deduplicate_removes_dupes(session: Session) -> None:
    before = len(session.tables["file-001::明细"])
    res = handle_deduplicate(
        ToolCall(
            tool_use_id="d1",
            name="tablex_deduplicate",
            input={"file_id": "file-001", "sheet": "明细", "key_columns": ["订单号"]},
        ),
        session,
    )
    assert res.success
    assert len(session.tables["file-001::明细"]) < before


def test_handle_deduplicate_missing_column(session: Session) -> None:
    res = handle_deduplicate(
        ToolCall(
            tool_use_id="d1",
            name="tablex_deduplicate",
            input={"file_id": "file-001", "sheet": "明细", "key_columns": ["nope"]},
        ),
        session,
    )
    assert not res.success


# ---------- handle_filter ----------


def test_handle_filter_creates_output_sheet(session: Session) -> None:
    res = handle_filter(
        ToolCall(
            tool_use_id="f1",
            name="tablex_filter",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "conditions": [{"column": "部门", "operator": "eq", "value": "研发"}],
            },
        ),
        session,
    )
    assert res.success
    assert "筛选结果" in session.tables


def test_handle_filter_invalid_condition(session: Session) -> None:
    res = handle_filter(
        ToolCall(
            tool_use_id="f1",
            name="tablex_filter",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "conditions": [{"column": "nope", "operator": "eq", "value": "x"}],
            },
        ),
        session,
    )
    assert not res.success


# ---------- handle_group_summary ----------


def test_handle_group_summary_creates_output(session: Session) -> None:
    res = handle_group_summary(
        ToolCall(
            tool_use_id="g1",
            name="tablex_group_summary",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "group_by": ["部门"],
                "metrics": {"金额": ["sum"]},
            },
        ),
        session,
    )
    assert res.success
    assert "汇总结果" in session.tables


def test_handle_group_summary_missing_group_col(session: Session) -> None:
    res = handle_group_summary(
        ToolCall(
            tool_use_id="g1",
            name="tablex_group_summary",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "group_by": ["nope"],
                "metrics": {"金额": ["sum"]},
            },
        ),
        session,
    )
    assert not res.success


# ---------- handle_compare ----------


def test_handle_compare_writes_output_sheet(session: Session) -> None:
    # Create two deduped copies (no duplicate key columns).
    from backend.app.domain.executor import INTERNAL_COL

    src = session.tables["file-001::明细"].drop_duplicates(subset=["订单号"]).reset_index(drop=True)
    left = src.copy()
    right = src.copy()
    right["金额"] = right["金额"].astype(object)
    right.loc[right["订单号"] == "A001", "金额"] = "9,999"
    session.tables["file-L::明细"] = left
    session.tables["file-R::明细"] = right

    res = handle_compare(
        ToolCall(
            tool_use_id="c1",
            name="tablex_compare",
            input={
                "left_ref": "file-L::明细",
                "right_ref": "file-R::明细",
                "key_columns": ["订单号"],
            },
        ),
        session,
    )
    assert res.success
    assert "对比结果" in session.tables


def test_handle_compare_missing_ref(session: Session) -> None:
    res = handle_compare(
        ToolCall(
            tool_use_id="c1",
            name="tablex_compare",
            input={
                "left_ref": "missing::x",
                "right_ref": "file-001::明细",
                "key_columns": ["订单号"],
            },
        ),
        session,
    )
    assert not res.success


# ---------- handle_fill_formula ----------


def test_handle_fill_formula_success(session: Session) -> None:
    res = handle_fill_formula(
        ToolCall(
            tool_use_id="ff1",
            name="tablex_fill_formula",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "target_column": "金额",
                "expression": "{金额}*2",
                "start_row": 2,
                "end_row": 10,
            },
        ),
        session,
    )
    assert res.success


def test_handle_fill_formula_invalid_expression(session: Session) -> None:
    res = handle_fill_formula(
        ToolCall(
            tool_use_id="ff1",
            name="tablex_fill_formula",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "target_column": "金额",
                "expression": "EVIL(1)",
                "start_row": 2,
                "end_row": 10,
            },
        ),
        session,
    )
    assert not res.success


# ---------- handle_sort ----------


def test_handle_sort_success(session: Session) -> None:
    res = handle_sort(
        ToolCall(
            tool_use_id="s1",
            name="tablex_sort",
            input={"file_id": "file-001", "sheet": "明细", "column": "金额", "order": "desc"},
        ),
        session,
    )
    assert res.success
    df = session.tables["file-001::明细"]
    nums = pd.to_numeric(df["金额"], errors="coerce").dropna().tolist()
    assert nums == sorted(nums, reverse=True)


def test_handle_sort_unknown_column(session: Session) -> None:
    res = handle_sort(
        ToolCall(
            tool_use_id="s1",
            name="tablex_sort",
            input={"file_id": "file-001", "sheet": "明细", "column": "nope"},
        ),
        session,
    )
    assert not res.success


# ---------- handle_fill_null ----------


def test_handle_fill_null_value_method(session: Session) -> None:
    res = handle_fill_null(
        ToolCall(
            tool_use_id="fn1",
            name="tablex_fill_null",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "column": "订单号",
                "method": "value",
                "value": "UNKNOWN",
            },
        ),
        session,
    )
    assert res.success


def test_handle_fill_null_mean_method(session: Session) -> None:
    res = handle_fill_null(
        ToolCall(
            tool_use_id="fn1",
            name="tablex_fill_null",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "column": "金额",
                "method": "mean",
            },
        ),
        session,
    )
    assert res.success


def test_handle_fill_null_ffill_method(session: Session) -> None:
    res = handle_fill_null(
        ToolCall(
            tool_use_id="fn1",
            name="tablex_fill_null",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "column": "订单号",
                "method": "ffill",
            },
        ),
        session,
    )
    assert res.success


def test_handle_fill_null_bfill_method(session: Session) -> None:
    res = handle_fill_null(
        ToolCall(
            tool_use_id="fn1",
            name="tablex_fill_null",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "column": "订单号",
                "method": "bfill",
            },
        ),
        session,
    )
    assert res.success


def test_handle_fill_null_unknown_method(session: Session) -> None:
    res = handle_fill_null(
        ToolCall(
            tool_use_id="fn1",
            name="tablex_fill_null",
            input={
                "file_id": "file-001",
                "sheet": "明细",
                "column": "订单号",
                "method": "magic",
            },
        ),
        session,
    )
    assert not res.success


# ---------- handle_export ----------


def test_handle_export_writes_file_and_returns_id(session: Session, tmp_path: Path) -> None:
    session.output_dir = tmp_path / "outputs"
    session.output_dir.mkdir(parents=True, exist_ok=True)
    res = handle_export(ToolCall(tool_use_id="e1", name="tablex_export", input={}), session)
    assert res.success
    assert res.data is not None
    out_id = res.data["output_id"]
    assert (tmp_path / "outputs" / f"{out_id}.xlsx").exists()
    assert session.output_id == out_id


def test_handle_export_empty_tables(tmp_path: Path) -> None:
    s = Session("s", tmp_path / "out")
    res = handle_export(ToolCall(tool_use_id="e1", name="tablex_export", input={}), s)
    assert not res.success


# ---------- truncate_result ----------


def test_truncate_result_small_passthrough() -> None:
    r = ToolResult(success=True, summary="ok")
    assert "summary" in truncate_result(r, MAX_RESULT_BYTES)


def test_truncate_result_drops_data_when_too_big() -> None:
    huge = {"x": "y" * 5000}
    r = ToolResult(success=True, summary="ok", data=huge)
    out = truncate_result(r, 200)
    assert "summary" in out
    assert "y" * 100 not in out