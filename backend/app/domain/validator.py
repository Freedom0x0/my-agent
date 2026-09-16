"""Validation business logic for tablex_validate."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd


RuleType = Literal[
    "primary_key", "foreign_key", "range", "format", "enum", "not_null",
]


class ValidationError(ValueError):
    """Raised when a rule configuration is invalid."""


@dataclass
class ValidationResult:
    column: str
    type: str
    passed: int
    failed: int
    failed_rows: list[int] = field(default_factory=list)
    error_samples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "type": self.type,
            "passed": self.passed,
            "failed": self.failed,
            "failed_rows": self.failed_rows[:200],
            "error_samples": self.error_samples[:20],
        }


def validate(df: pd.DataFrame, rules: list[dict[str, Any]]) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for rule in rules:
        rtype = rule.get("type")
        column = rule.get("column")
        if not rtype or not column:
            raise ValidationError(f"rule 缺少必要字段: {rule}")
        if rtype == "primary_key":
            results.append(_check_primary_key(df, column))
        elif rtype == "foreign_key":
            results.append(_check_foreign_key(df, column, rule.get("ref") or {}))
        elif rtype == "range":
            results.append(_check_range(df, column, rule.get("min"), rule.get("max")))
        elif rtype == "format":
            results.append(_check_format(df, column, rule.get("pattern", "")))
        elif rtype == "enum":
            results.append(_check_enum(df, column, rule.get("values") or []))
        elif rtype == "not_null":
            results.append(_check_not_null(df, column))
        else:
            raise ValidationError(f"不支持的 rule 类型: {rtype}")
    return results


def _is_null(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _check_not_null(df: pd.DataFrame, column: str) -> ValidationResult:
    if column not in df.columns:
        raise ValidationError(f"列不存在: {column}")
    mask = df[column].apply(_is_null)
    failed_idx = df.index[mask].tolist()
    failed = len(failed_idx)
    passed = len(df) - failed
    return ValidationResult(
        column=column, type="not_null",
        passed=passed, failed=failed,
        failed_rows=failed_idx,
        error_samples=_sample(df, column, mask),
    )


def _check_primary_key(df: pd.DataFrame, column: str) -> ValidationResult:
    not_null = _check_not_null(df, column)
    if not_null.failed > 0:
        return ValidationResult(
            column=column, type="primary_key",
            passed=0, failed=not_null.failed,
            failed_rows=not_null.failed_rows,
            error_samples=not_null.error_samples,
        )
    dup_mask = df[column].duplicated(keep=False)
    failed_idx = df.index[dup_mask].tolist()
    failed = len(failed_idx)
    passed = len(df) - failed
    return ValidationResult(
        column=column, type="primary_key",
        passed=passed, failed=failed,
        failed_rows=failed_idx,
        error_samples=_sample(df, column, dup_mask),
    )


def _check_foreign_key(
    df: pd.DataFrame, column: str, ref: dict[str, Any],
) -> ValidationResult:
    if column not in df.columns:
        raise ValidationError(f"列不存在: {column}")
    target = ref.get("values")
    if target is None:
        raise ValidationError("foreign_key rule 需要提供 values (参考表的主键集合)")
    target_set = {str(v) for v in target if v is not None}

    def ok(v: Any) -> bool:
        return not _is_null(v) and str(v) in target_set

    mask = ~df[column].apply(ok)
    failed_idx = df.index[mask].tolist()
    failed = len(failed_idx)
    passed = len(df) - failed
    return ValidationResult(
        column=column, type="foreign_key",
        passed=passed, failed=failed,
        failed_rows=failed_idx,
        error_samples=_sample(df, column, mask),
    )


def _check_range(
    df: pd.DataFrame, column: str, min_v: Any, max_v: Any,
) -> ValidationResult:
    if column not in df.columns:
        raise ValidationError(f"列不存在: {column}")
    series = df[column]

    def ok(v: Any) -> bool:
        if _is_null(v):
            return True
        try:
            num = float(v)
        except (TypeError, ValueError):
            return False
        if min_v is not None and num < float(min_v):
            return False
        if max_v is not None and num > float(max_v):
            return False
        return True

    mask = ~series.apply(ok)
    failed_idx = df.index[mask].tolist()
    failed = len(failed_idx)
    passed = len(df) - failed
    return ValidationResult(
        column=column, type="range",
        passed=passed, failed=failed,
        failed_rows=failed_idx,
        error_samples=_sample(df, column, mask),
    )


def _check_format(df: pd.DataFrame, column: str, pattern: str) -> ValidationResult:
    if column not in df.columns:
        raise ValidationError(f"列不存在: {column}")
    if not pattern:
        raise ValidationError("format rule 需要提供 pattern")
    compiled = re.compile(pattern)

    def ok(v: Any) -> bool:
        if _is_null(v):
            return True
        return compiled.match(str(v)) is not None

    mask = ~df[column].apply(ok)
    failed_idx = df.index[mask].tolist()
    failed = len(failed_idx)
    passed = len(df) - failed
    return ValidationResult(
        column=column, type="format",
        passed=passed, failed=failed,
        failed_rows=failed_idx,
        error_samples=_sample(df, column, mask),
    )


def _check_enum(df: pd.DataFrame, column: str, values: list[Any]) -> ValidationResult:
    if column not in df.columns:
        raise ValidationError(f"列不存在: {column}")
    val_set = {str(v) for v in values}

    def ok(v: Any) -> bool:
        if _is_null(v):
            return True
        return str(v) in val_set

    mask = ~df[column].apply(ok)
    failed_idx = df.index[mask].tolist()
    failed = len(failed_idx)
    passed = len(df) - failed
    return ValidationResult(
        column=column, type="enum",
        passed=passed, failed=failed,
        failed_rows=failed_idx,
        error_samples=_sample(df, column, mask),
    )


def _sample(df: pd.DataFrame, column: str, mask: pd.Series) -> list[str]:
    if not mask.any():
        return []
    return [str(v) for v in df.loc[mask, column].head(20).tolist()]