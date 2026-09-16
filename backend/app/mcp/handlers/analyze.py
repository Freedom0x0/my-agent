"""tablex_analyze handler."""
from __future__ import annotations

from typing import Any

from ...domain.analyzer import (
    AnalysisError,
    correlation,
    detect_outliers,
    linear_regression,
    moving_avg,
)
from ..schemas import ToolCall, ToolResult
from ._base import HandlerSpec, _fail, _ok


_OPS = {"correlation", "outlier", "regression", "moving_avg"}


def handle_analyze(tool_call: ToolCall, session: Any) -> ToolResult:
    file_id = tool_call.input["file_id"]
    sheet = tool_call.input["sheet"]
    operation = tool_call.input.get("operation", "correlation")
    params = tool_call.input.get("params") or {}

    sheet_ref = f"{file_id}::{sheet}"
    if sheet_ref not in session.tables:
        return _fail(f"工作表未加载: {sheet_ref}")
    if operation not in _OPS:
        return _fail(f"不支持的操作: {operation}")

    df = session.tables[sheet_ref]

    try:
        if operation == "correlation":
            columns = params.get("columns") or []
            if len(columns) < 2:
                return _fail("correlation 至少需要 2 个列")
            method = params.get("method", "pearson")
            matrix = correlation(df, columns, method=method)
            return _ok(
                f"相关性（{method}）：{len(columns)} 列",
                data={"operation": operation, "method": method, "matrix": matrix},
            )
        if operation == "outlier":
            columns = params.get("columns") or []
            if not columns:
                return _fail("outlier 必须提供 columns")
            threshold = float(params.get("threshold", 3.0))
            method = params.get("method", "zscore")
            result = detect_outliers(df, columns, threshold=threshold, method=method)
            total = sum(len(v) for v in result.values())
            return _ok(
                f"异常检测：{total} 个异常点（阈值 {threshold}）",
                data={
                    "operation": operation,
                    "method": method,
                    "threshold": threshold,
                    "outliers": result,
                    "total_outliers": total,
                },
            )
        if operation == "regression":
            x = params.get("x")
            y = params.get("y")
            if not x or not y:
                return _fail("regression 必须提供 x 和 y")
            result = linear_regression(df, x, y)
            return _ok(
                f"线性回归：y={result['slope']:.4f}·x+{result['intercept']:.4f}，R²={result['r_squared']:.4f}",
                data={"operation": operation, "x": x, "y": y, "result": result},
            )
        # moving_avg
        column = params.get("column")
        if not column:
            return _fail("moving_avg 必须提供 column")
        window = int(params.get("window", 7))
        series = moving_avg(df, column, window=window)
        return _ok(
            f"移动平均：{column}（窗口 {window}）",
            data={
                "operation": operation,
                "column": column,
                "window": window,
                "values": series.tolist(),
            },
        )
    except AnalysisError as exc:
        return _fail(str(exc))


HANDLERS = {
    "tablex_analyze": HandlerSpec(
        "tablex_analyze", ["file_id", "sheet", "operation"], handle_analyze,
    ),
}
