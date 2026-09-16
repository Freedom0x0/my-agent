"""Tests for tablex_analyze handler + analyzer domain."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.mcp.handlers import handle_analyze
from backend.app.mcp.schemas import ToolCall
from backend.app.mcp.session import Session
from backend.app.domain.analyzer import (
    correlation,
    detect_outliers,
    linear_regression,
    moving_avg,
    AnalysisError,
)


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    s = Session("s", tmp_path / "out")
    rng = np.random.default_rng(42)
    xs = np.arange(50, dtype=float)
    ys = 2.0 * xs + rng.normal(0, 1, 50)
    # Inject one outlier strong enough to clear z-score=3 but mild enough
    # not to dominate the linear regression slope.
    ys[10] += 500
    s.tables["file-A::d"] = pd.DataFrame({
        "x": xs,
        "y": ys,
        "z": rng.normal(0, 1, 50),
    })
    return s


# ---------- domain ----------


def test_correlation_pearson() -> None:
    df = pd.DataFrame({"a": [1, 2, 3, 4], "b": [2, 4, 6, 8]})
    out = correlation(df, ["a", "b"], method="pearson")
    assert abs(out["a"]["b"] - 1.0) < 1e-6


def test_correlation_missing_column() -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(AnalysisError):
        correlation(df, ["a", "nope"])


def test_detect_outliers_zscore() -> None:
    df = pd.DataFrame({"v": [1, 1, 1, 1, 1, 100, 1, 1]})
    out = detect_outliers(df, ["v"], threshold=2.0)
    assert 5 in out["v"]


def test_detect_outliers_iqr() -> None:
    df = pd.DataFrame({"v": [1, 2, 3, 4, 5, 100]})
    out = detect_outliers(df, ["v"], threshold=1.5, method="iqr")
    assert 5 in out["v"]


def test_linear_regression_basic() -> None:
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [2, 4, 6, 8, 10]})
    res = linear_regression(df, "x", "y")
    assert abs(res["slope"] - 2.0) < 1e-6
    assert abs(res["intercept"]) < 1e-6
    assert abs(res["r_squared"] - 1.0) < 1e-6


def test_linear_regression_insufficient_data() -> None:
    df = pd.DataFrame({"x": [1.0], "y": [1.0]})
    with pytest.raises(AnalysisError):
        linear_regression(df, "x", "y")


def test_moving_avg() -> None:
    df = pd.DataFrame({"v": [1, 2, 3, 4, 5]})
    out = moving_avg(df, "v", window=3)
    # First value uses min_periods=1, then rolling starts at index 2.
    assert out.iloc[-1] == pytest.approx(4.0)


def test_moving_avg_invalid_window() -> None:
    df = pd.DataFrame({"v": [1, 2]})
    with pytest.raises(AnalysisError):
        moving_avg(df, "v", window=0)


# ---------- handler ----------


def test_handle_analyze_correlation(session: Session) -> None:
    res = handle_analyze(
        ToolCall(
            tool_use_id="a1", name="tablex_analyze",
            input={
                "file_id": "file-A", "sheet": "d",
                "operation": "correlation",
                "params": {"columns": ["x", "y"], "method": "pearson"},
            },
        ),
        session,
    )
    assert res.success
    assert "matrix" in res.data


def test_handle_analyze_outlier(session: Session) -> None:
    res = handle_analyze(
        ToolCall(
            tool_use_id="a1", name="tablex_analyze",
            input={
                "file_id": "file-A", "sheet": "d",
                "operation": "outlier",
                "params": {"columns": ["y"], "threshold": 3.0, "method": "zscore"},
            },
        ),
        session,
    )
    assert res.success
    assert 10 in res.data["outliers"]["y"]


def test_handle_analyze_regression(session: Session) -> None:
    res = handle_analyze(
        ToolCall(
            tool_use_id="a1", name="tablex_analyze",
            input={
                "file_id": "file-A", "sheet": "d",
                "operation": "regression",
                "params": {"x": "x", "y": "y"},
            },
        ),
        session,
    )
    assert res.success
    assert abs(res.data["result"]["slope"] - 2.0) < 1.0  # noisy but close


def test_handle_analyze_moving_avg(session: Session) -> None:
    res = handle_analyze(
        ToolCall(
            tool_use_id="a1", name="tablex_analyze",
            input={
                "file_id": "file-A", "sheet": "d",
                "operation": "moving_avg",
                "params": {"column": "y", "window": 5},
            },
        ),
        session,
    )
    assert res.success
    assert len(res.data["values"]) == 50


def test_handle_analyze_invalid_operation(session: Session) -> None:
    res = handle_analyze(
        ToolCall(
            tool_use_id="a1", name="tablex_analyze",
            input={"file_id": "file-A", "sheet": "d", "operation": "fft"},
        ),
        session,
    )
    assert not res.success


def test_handle_analyze_unknown_sheet(session: Session) -> None:
    res = handle_analyze(
        ToolCall(
            tool_use_id="a1", name="tablex_analyze",
            input={"file_id": "file-A", "sheet": "nope", "operation": "correlation",
                   "params": {"columns": ["x", "y"]}},
        ),
        session,
    )
    assert not res.success
