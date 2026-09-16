"""Tests for tablex_read_chunk handler + streaming domain."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.app.mcp.handlers import handle_read_chunk
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session
from backend.app.domain.streaming import read_chunk, total_rows


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    s = Session("s", tmp_path / "out")
    s.tables["file-A::data"] = pd.DataFrame({
        "x": list(range(20)),
        "y": [i * 2 for i in range(20)],
        "z": [f"row{i}" for i in range(20)],
    })
    return s


# ---------- domain ----------


def test_read_chunk_basic() -> None:
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]})
    out = read_chunk(df, offset=1, limit=2)
    assert len(out) == 2
    assert out.iloc[0]["a"] == 2


def test_read_chunk_with_columns() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    out = read_chunk(df, offset=0, limit=3, columns=["a"])
    assert list(out.columns) == ["a"]
    assert len(out) == 3


def test_read_chunk_missing_column() -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(KeyError):
        read_chunk(df, offset=0, limit=10, columns=["nope"])


def test_read_chunk_negative_offset() -> None:
    df = pd.DataFrame({"a": [1, 2]})
    with pytest.raises(ValueError):
        read_chunk(df, offset=-1, limit=1)


def test_total_rows() -> None:
    df = pd.DataFrame({"a": [1, 2, 3]})
    assert total_rows(df) == 3


# ---------- handler ----------


def test_handle_read_chunk_basic(session: Session) -> None:
    res = handle_read_chunk(
        ToolCall(
            tool_use_id="c1", name="tablex_read_chunk",
            input={"file_id": "file-A", "sheet": "data", "offset": 0, "limit": 5},
        ),
        session,
    )
    assert res.success
    assert res.data is not None
    assert res.data["returned"] == 5
    assert res.data["total_rows"] == 20
    assert len(res.data["rows"]) == 5


def test_handle_read_chunk_with_columns(session: Session) -> None:
    res = handle_read_chunk(
        ToolCall(
            tool_use_id="c1", name="tablex_read_chunk",
            input={"file_id": "file-A", "sheet": "data", "columns": ["x"]},
        ),
        session,
    )
    assert res.success
    assert all(set(r.keys()) == {"x"} for r in res.data["rows"])


def test_handle_read_chunk_unknown_sheet(session: Session) -> None:
    res = handle_read_chunk(
        ToolCall(
            tool_use_id="c1", name="tablex_read_chunk",
            input={"file_id": "file-A", "sheet": "nope"},
        ),
        session,
    )
    assert not res.success


def test_handle_read_chunk_offset_beyond(session: Session) -> None:
    res = handle_read_chunk(
        ToolCall(
            tool_use_id="c1", name="tablex_read_chunk",
            input={"file_id": "file-A", "sheet": "data", "offset": 100, "limit": 10},
        ),
        session,
    )
    assert res.success
    assert res.data["returned"] == 0
