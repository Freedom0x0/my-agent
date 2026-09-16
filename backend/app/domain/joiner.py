"""Join business logic for tablex_join."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


class JoinError(ValueError):
    """Raised when join parameters are invalid."""


How = Literal["inner", "left", "right", "full"]


@dataclass
class JoinMeta:
    left_count: int
    right_count: int
    matched: int
    unmatched_left: int
    unmatched_right: int
    how: str
    on: str | None = None
    left_on: str | None = None
    right_on: str | None = None


def join_tables(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: str | None = None,
    left_on: str | None = None,
    right_on: str | None = None,
    how: How = "inner",
    suffix: tuple[str, str] = ("_l", "_r"),
) -> tuple[pd.DataFrame, JoinMeta]:
    if not on and not (left_on and right_on):
        raise JoinError("必须提供 on 或 left_on+right_on")
    if on and (left_on or right_on):
        raise JoinError("on 与 left_on/right_on 不能同时提供")
    if how not in {"inner", "left", "right", "full", "outer"}:
        raise JoinError(f"不支持的连接方式: {how}")

    if on:
        if on not in left.columns:
            raise JoinError(f"左表缺少列: {on}")
        if on not in right.columns:
            raise JoinError(f"右表缺少列: {on}")
    else:
        if left_on not in left.columns:
            raise JoinError(f"左表缺少列: {left_on}")
        if right_on not in right.columns:
            raise JoinError(f"右表缺少列: {right_on}")

    pd_how = "outer" if how == "full" else how
    left_keys = set(left[on or left_on].tolist())
    right_keys = set(right[on or right_on].tolist())
    matched = len(left_keys & right_keys)
    unmatched_left = len(left_keys - right_keys)
    unmatched_right = len(right_keys - left_keys)

    merged = pd.merge(
        left,
        right,
        on=on,
        left_on=left_on,
        right_on=right_on,
        how=pd_how,
        suffixes=suffix,
    )

    meta = JoinMeta(
        left_count=len(left),
        right_count=len(right),
        matched=matched,
        unmatched_left=unmatched_left,
        unmatched_right=unmatched_right,
        how=how,
        on=on,
        left_on=left_on,
        right_on=right_on,
    )
    return merged, meta


def _key_values(df: pd.DataFrame, column: str) -> list:
    return df[column].tolist()