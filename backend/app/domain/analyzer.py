"""Advanced analysis: correlation, outlier detection, regression, moving average.

ponytail: scipy is the only non-stdlib dep (linregress). If scipy is missing
at runtime, fall back to a pure-statsmodels-free numpy implementation of
ordinary least squares. Upgrade path: add Spearman rank corr option that
doesn't require scipy (use pandas .corr(method='spearman') which it does
natively — already wired).
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

Method = Literal["pearson", "spearman"]


class AnalysisError(ValueError):
    """Raised when analysis parameters are invalid or computation fails."""


def correlation(df: pd.DataFrame, columns: list[str], method: str = "pearson") -> dict[str, Any]:
    """Return correlation matrix as a dict of {col_a: {col_b: r, ...}, ...}."""
    _check_columns(df, columns)
    if method not in {"pearson", "spearman"}:
        raise AnalysisError(f"不支持的相关性方法: {method}")
    # coerce to numeric (non-numeric become NaN; corr skips NaN pairwise)
    numeric = df[columns].apply(pd.to_numeric, errors="coerce")
    matrix = numeric.corr(method=method).round(4)
    return matrix.to_dict()


def detect_outliers(
    df: pd.DataFrame,
    columns: list[str],
    threshold: float = 3.0,
    method: str = "zscore",
) -> dict[str, list[int]]:
    """Return outlier row indices per column.

    method='zscore': |z| > threshold (default)
    method='iqr': values outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
    """
    _check_columns(df, columns)
    if threshold <= 0:
        raise AnalysisError("threshold 必须为正数")

    out: dict[str, list[int]] = {}
    if method == "zscore":
        for col in columns:
            series = pd.to_numeric(df[col], errors="coerce")
            mean = series.mean()
            std = series.std()
            if std == 0 or pd.isna(std):
                out[col] = []
                continue
            z = (series - mean) / std
            mask = z.abs() > threshold
            out[col] = df.index[mask.fillna(False)].tolist()
    elif method == "iqr":
        for col in columns:
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            if series.empty:
                out[col] = []
                continue
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            numeric = pd.to_numeric(df[col], errors="coerce")
            mask = (numeric < lo) | (numeric > hi)
            out[col] = df.index[mask.fillna(False)].tolist()
    else:
        raise AnalysisError(f"不支持的异常检测方法: {method}")
    return out


def linear_regression(df: pd.DataFrame, x: str, y: str) -> dict[str, float]:
    """Ordinary least squares regression; returns slope/intercept/r²/p-value/std_err."""
    _check_columns(df, [x, y])
    xs = pd.to_numeric(df[x], errors="coerce").dropna()
    ys = pd.to_numeric(df[y], errors="coerce").dropna()
    common = xs.index.intersection(ys.index)
    if len(common) < 2:
        raise AnalysisError(f"回归至少需要 2 个有效数据点，当前 {len(common)} 个")
    xs, ys = xs.loc[common].to_numpy(dtype=float), ys.loc[common].to_numpy(dtype=float)

    try:
        from scipy.stats import linregress
        result = linregress(xs, ys)
        return {
            "slope": float(result.slope),
            "intercept": float(result.intercept),
            "r_squared": float(result.rvalue ** 2),
            "p_value": float(result.pvalue),
            "std_err": float(result.stderr),
            "n": int(len(common)),
        }
    except ImportError:
        # ponytail: pure-numpy OLS fallback so the tool works without scipy.
        # scipy.stats.linregress adds p-value + std_err; if scipy is missing
        # we report only the basic OLS fit.
        n = len(xs)
        x_mean, y_mean = xs.mean(), ys.mean()
        ss_xy = float(np.sum((xs - x_mean) * (ys - y_mean)))
        ss_xx = float(np.sum((xs - x_mean) ** 2))
        if ss_xx == 0:
            raise AnalysisError("x 列方差为零，无法拟合回归") from None
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        y_pred = slope * xs + intercept
        ss_res = float(np.sum((ys - y_pred) ** 2))
        ss_tot = float(np.sum((ys - y_mean) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return {
            "slope": slope,
            "intercept": intercept,
            "r_squared": r2,
            "p_value": float("nan"),
            "std_err": float("nan"),
            "n": int(n),
        }


def moving_avg(df: pd.DataFrame, column: str, window: int) -> pd.Series:
    """Rolling moving average; min_periods=1 so the leading edge is filled."""
    _check_columns(df, [column])
    if window < 1:
        raise AnalysisError("window 必须 >= 1")
    series = pd.to_numeric(df[column], errors="coerce")
    return series.rolling(window=window, min_periods=1).mean()


def _check_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise AnalysisError(f"列不存在: {missing}")
