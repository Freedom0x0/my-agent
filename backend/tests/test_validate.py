"""Tests for tablex_validate handler and validator domain."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.app.mcp.handlers import handle_validate
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session, SessionStore
from backend.app.domain.validator import ValidationError, validate, _check_not_null, _check_primary_key


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    store = SessionStore(tmp_path / "out")
    store.output_dir.mkdir(parents=True, exist_ok=True)
    s = store.get_or_create("sess-val")
    s.tables["file-V::数据"] = pd.DataFrame({
        "id": [1, 2, 3, 4],
        "email": ["a@b.com", "bad", "c@d.com", None],
        "age": [25, 200, 40, -5],
        "category": ["A", "B", "X", "A"],
    })
    return s


# ---------- domain ----------


def test_check_not_null_pass_and_fail() -> None:
    df = pd.DataFrame({"a": [1, None, 3]})
    r = _check_not_null(df, "a")
    assert r.passed == 2
    assert r.failed == 1


def test_check_primary_key_dup() -> None:
    df = pd.DataFrame({"id": [1, 2, 2, 3]})
    r = _check_primary_key(df, "id")
    assert r.failed == 2
    df2 = pd.DataFrame({"id": [1, 2, 3]})
    r2 = _check_primary_key(df2, "id")
    assert r2.passed == 3


def test_validate_all_rule_types() -> None:
    df = pd.DataFrame({
        "id": [1, 2, 2],
        "ref": [10, 20, 30],
        "age": [-1, 50, 200],
        "email": ["ok@x.com", "bad", "ok@y.com"],
        "cat": ["A", "B", "Z"],
        "name": ["x", "y", None],
    })
    rules = [
        {"column": "id", "type": "primary_key"},
        {"column": "ref", "type": "foreign_key", "ref": {"values": [10, 20]}},
        {"column": "age", "type": "range", "min": 0, "max": 150},
        {"column": "email", "type": "format", "pattern": r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$"},
        {"column": "cat", "type": "enum", "values": ["A", "B", "C"]},
        {"column": "name", "type": "not_null"},
    ]
    results = validate(df, rules)
    assert len(results) == 6
    types = {r.type for r in results}
    assert types == {"primary_key", "foreign_key", "range", "format", "enum", "not_null"}


def test_validate_unknown_type() -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(ValidationError):
        validate(df, [{"column": "a", "type": "wat"}])


# ---------- handler ----------


def test_handle_validate_report_only(session: Session) -> None:
    res = handle_validate(
        ToolCall(
            tool_use_id="v1", name="tablex_validate",
            input={
                "file_id": "file-V", "sheet": "数据",
                "rules": [
                    {"column": "email", "type": "format", "pattern": r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$"},
                    {"column": "age", "type": "range", "min": 0, "max": 150},
                ],
                "fail_strategy": "report_only",
            },
        ),
        session,
    )
    assert res.success
    assert res.data is not None
    assert res.data["passed"] + res.data["failed"] > 0


def test_handle_validate_mark(session: Session) -> None:
    res = handle_validate(
        ToolCall(
            tool_use_id="v1", name="tablex_validate",
            input={
                "file_id": "file-V", "sheet": "数据",
                "rules": [
                    {"column": "email", "type": "format", "pattern": r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$"},
                ],
                "fail_strategy": "mark",
            },
        ),
        session,
    )
    assert res.success
    assert "validate_marked" in session.tables


def test_handle_validate_filter(session: Session) -> None:
    res = handle_validate(
        ToolCall(
            tool_use_id="v1", name="tablex_validate",
            input={
                "file_id": "file-V", "sheet": "数据",
                "rules": [
                    {"column": "email", "type": "format", "pattern": r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$"},
                    {"column": "age", "type": "range", "min": 0, "max": 150},
                ],
                "fail_strategy": "filter",
            },
        ),
        session,
    )
    assert res.success
    assert res.data is not None
    assert res.data["rows"] < 4


def test_handle_validate_no_rules(session: Session) -> None:
    res = handle_validate(
        ToolCall(
            tool_use_id="v1", name="tablex_validate",
            input={"file_id": "file-V", "sheet": "数据", "rules": []},
        ),
        session,
    )
    assert not res.success


def test_handle_validate_unknown_strategy(session: Session) -> None:
    res = handle_validate(
        ToolCall(
            tool_use_id="v1", name="tablex_validate",
            input={
                "file_id": "file-V", "sheet": "数据",
                "rules": [{"column": "id", "type": "not_null"}],
                "fail_strategy": "wat",
            },
        ),
        session,
    )
    assert not res.success


def test_handle_validate_unknown_sheet(session: Session) -> None:
    res = handle_validate(
        ToolCall(
            tool_use_id="v1", name="tablex_validate",
            input={
                "file_id": "file-V", "sheet": "nope",
                "rules": [{"column": "id", "type": "not_null"}],
            },
        ),
        session,
    )
    assert not res.success