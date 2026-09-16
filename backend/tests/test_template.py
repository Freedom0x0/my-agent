"""Tests for tablex_template_fill handler + template domain."""
from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from backend.app.domain.template import fill_template
from backend.app.mcp.handlers import handle_template_fill
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session


def _make_template(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Letter"
    ws["A1"] = "Hello {{name}}"
    ws["A2"] = "Today is {{date}}"
    ws["A3"] = "Unknown: {{missing}}"
    out = tmp_path / "tpl.xlsx"
    wb.save(out)
    return out


# ---------- domain ----------


def test_fill_template_happy(tmp_path: Path) -> None:
    path = _make_template(tmp_path)
    wb = load_workbook(path)
    replaced, missing = fill_template(wb, "Letter", {"name": "张三", "date": "2026-09-16"})
    assert replaced == 2
    assert missing == ["missing"]
    assert wb["Letter"]["A1"].value == "Hello 张三"
    assert wb["Letter"]["A3"].value == "Unknown: {{missing}}"


def test_fill_template_unknown_sheet(tmp_path: Path) -> None:
    path = _make_template(tmp_path)
    wb = load_workbook(path)
    from backend.app.domain.template import TemplateError
    with pytest.raises(TemplateError):
        fill_template(wb, "Nope", {})


def test_fill_template_no_placeholders(tmp_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "plain text"
    replaced, missing = fill_template(wb, "Sheet", {"x": "1"})
    assert replaced == 0
    assert missing == []


# ---------- handler ----------


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    s = Session("s", tmp_path / "out")
    path = _make_template(tmp_path)
    s.files["file-T"] = {"path": str(path), "sha256": "x", "original_name": "tpl.xlsx"}
    return s


def test_handle_template_fill_success(session: Session) -> None:
    res = handle_template_fill(
        ToolCall(
            tool_use_id="t1", name="tablex_template_fill",
            input={
                "template_file_id": "file-T",
                "data": {"name": "张三", "date": "2026-09-16"},
            },
        ),
        session,
    )
    assert res.success
    assert res.data["replaced_count"] == 2
    assert "missing" in res.data["missing_keys"]


def test_handle_template_fill_with_sheet(session: Session) -> None:
    res = handle_template_fill(
        ToolCall(
            tool_use_id="t1", name="tablex_template_fill",
            input={
                "template_file_id": "file-T",
                "data": {"name": "X", "date": "Y"},
                "sheet": "Letter",
            },
        ),
        session,
    )
    assert res.success


def test_handle_template_fill_missing_file(session: Session) -> None:
    res = handle_template_fill(
        ToolCall(
            tool_use_id="t1", name="tablex_template_fill",
            input={"template_file_id": "missing", "data": {}},
        ),
        session,
    )
    assert not res.success


def test_handle_template_fill_no_data(session: Session) -> None:
    res = handle_template_fill(
        ToolCall(
            tool_use_id="t1", name="tablex_template_fill",
            input={"template_file_id": "file-T", "data": {"name": "X", "date": "Y"}},
        ),
        session,
    )
    assert res.success
    assert res.data["missing_keys"] == ["missing"]
