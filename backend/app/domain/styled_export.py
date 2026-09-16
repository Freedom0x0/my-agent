"""Apply visual styles to an openpyxl worksheet: header fills/fonts, freeze,
auto column width, conditional highlight, merged cells.
"""
from __future__ import annotations

import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ponytail: simple expression evaluator for highlight rules.
# Supports: > N, >= N, < N, <= N, == N, == "text", != N, contains "x".
# Upgrade path: ship a tiny AST-based evaluator if requirements grow
# (regex, lambdas, between, etc.).
_CONDITION = re.compile(r"^\s*(>=|<=|>|<|==|!=)\s*(.+?)\s*$")


class StyleError(ValueError):
    """Raised when a style spec is malformed."""


def _strip_hash(color: str) -> str:
    return color.lstrip("#")


def _apply_header_style(ws: Any, header_spec: dict[str, Any]) -> None:
    bold = bool(header_spec.get("bold", False))
    bg = _strip_hash(str(header_spec.get("bg_color", ""))) or None
    fg = _strip_hash(str(header_spec.get("font_color", ""))) or None
    font = Font(bold=bold, color=fg)
    fill = PatternFill("solid", fgColor=bg) if bg else None
    for cell in ws[1]:
        if font:
            cell.font = font
        if fill:
            cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _apply_highlight_rules(ws: Any, rules: list[dict[str, Any]]) -> None:
    header = [c.value for c in ws[1]]
    for rule in rules:
        col_name = rule.get("column")
        condition = rule.get("condition")
        bg_color = _strip_hash(str(rule.get("bg_color", "")))
        if not (col_name and condition and bg_color):
            continue
        if col_name not in header:
            continue
        col_idx = header.index(col_name)
        fill = PatternFill("solid", fgColor=bg_color)
        for row in ws.iter_rows(min_row=2):
            cell = row[col_idx]
            if _eval_condition(cell.value, condition):
                cell.fill = fill


def _eval_condition(value: Any, condition: str) -> bool:
    match = _CONDITION.match(condition)
    if not match:
        return False
    op, raw = match.group(1), match.group(2)
    # Try numeric first; fall back to string compare.
    try:
        target = float(raw)
        if value is None:
            return False
        num = float(value)
    except (TypeError, ValueError):
        target = raw.strip().strip('"').strip("'")
        num = str(value) if value is not None else ""

    if op == ">":
        return num > target  # type: ignore[operator]
    if op == ">=":
        return num >= target
    if op == "<":
        return num < target
    if op == "<=":
        return num <= target
    if op == "==":
        return num == target  # type: ignore[comparison-overlap]
    if op == "!=":
        return num != target
    return False


def _auto_column_width(ws: Any) -> None:
    for col_cells in ws.columns:
        col_letter = get_column_letter(col_cells[0].column)
        max_len = 0
        for cell in col_cells:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 8), 60)


def _apply_merge_cells(ws: Any, merges: list[dict[str, Any]]) -> None:
    for merge in merges:
        rng = merge.get("range")
        value = merge.get("value")
        if not rng or ":" not in rng:
            continue
        ws.merge_cells(rng)
        anchor = rng.split(":")[0]
        if value is not None:
            ws[anchor] = value


def apply_styles(workbook: Workbook, sheet_name: str, style: dict[str, Any]) -> None:
    """Apply the full style spec to one sheet (in-place)."""
    if sheet_name not in workbook.sheetnames:
        raise StyleError(f"工作表不存在: {sheet_name}")
    ws = workbook[sheet_name]

    if style.get("header"):
        _apply_header_style(ws, style["header"])

    if style.get("highlight_rules"):
        _apply_highlight_rules(ws, style["highlight_rules"])

    if style.get("freeze_header"):
        ws.freeze_panes = "A2"

    if style.get("auto_column_width"):
        _auto_column_width(ws)

    if style.get("merge_cells"):
        _apply_merge_cells(ws, style["merge_cells"])
