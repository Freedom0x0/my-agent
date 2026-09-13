"""Deterministic demo planner - no network calls, no API key required."""
from __future__ import annotations

import re
from typing import Iterable

from ..schemas import (
    ColumnInspection,
    CompareOperation,
    CreateIssueSheetOperation,
    DeduplicateOperation,
    FillFormulaOperation,
    FilterCondition,
    FilterOperation,
    GroupSummaryOperation,
    NormalizeOperation,
    OperationPlan,
    SheetRef,
    SheetInspection,
    WorkbookInspection,
)


class AmbiguousRequestError(ValueError):
    """Raised when the planner cannot resolve required fields from inspection."""


COLUMN_ALIASES: dict[str, list[str]] = {
    "金额": ["金额", "金额合计", "费用", "销售额", "收入", "单价"],
    "部门": ["部门", "所属部门", "组织", "单位", "科室"],
    "日期": ["日期", "时间", "发生日期", "创建时间", "登记日期"],
    "编号": ["编号", "id", "编码", "订单号", "员工编号", "工单号", "项目编号"],
    "状态": ["状态", "进度", "处理状态"],
    "姓名": ["姓名", "名字", "人员"],
    "预算": ["预算", "预算金额", "目标金额"],
    "项目": ["项目", "项目名称"],
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def _find_column(sheet: SheetInspection, semantic: str) -> str | None:
    aliases = [semantic, *COLUMN_ALIASES.get(semantic, [])]
    norm_aliases = {_norm(a) for a in aliases}
    for col in sheet.columns:
        if _norm(col.name) in norm_aliases:
            return col.name
    for col in sheet.columns:
        if any(_norm(col.name).startswith(_norm(a)) for a in aliases):
            return col.name
    return None


def _resolve_columns(sheet: SheetInspection, semantics: Iterable[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for semantic in semantics:
        col = _find_column(sheet, semantic)
        if col is None:
            raise AmbiguousRequestError(f"未在工作表 {sheet.name} 找到对应 {semantic} 的列")
        resolved[semantic] = col
    return resolved


def _build_sheet_catalog(inspections: list[WorkbookInspection]) -> list[SheetRef]:
    catalog: list[SheetRef] = []
    for idx, insp in enumerate(inspections):
        file_id = f"file-{idx + 1:03d}"
        for sheet in insp.sheets:
            catalog.append(SheetRef(file_id=file_id, sheet_name=sheet.name, ref=f"{file_id}::{sheet.name}"))
    return catalog


def _pick_primary_sheet(inspections: list[WorkbookInspection]) -> tuple[SheetInspection, str]:
    best: tuple[int, SheetInspection, str] | None = None
    for idx, insp in enumerate(inspections):
        file_id = f"file-{idx + 1:03d}"
        for sheet in insp.sheets:
            score = sheet.row_count * (sheet.column_count or 1)
            if best is None or score > best[0]:
                best = (score, sheet, file_id)
    if best is None:
        raise AmbiguousRequestError("没有可用工作表")
    return best[1], best[2]


class DemoPlanner:
    """Rule-based planner used when no model API key is configured."""

    def plan(
        self,
        request: str,
        inspections: list[WorkbookInspection],
        sheet_catalog: list[SheetRef],
    ) -> OperationPlan:
        text = request or ""
        primary_sheet, primary_file_id = _pick_primary_sheet(inspections)
        primary_ref = f"{primary_file_id}::{primary_sheet.name}"
        plan_id = f"plan-{abs(hash(text)) & 0xffff_ffff:08x}"

        normalized = text.replace(" ", "")

        # Pattern 1: full cleanup + summarize + issue list
        if ("检查" in text or "体检" in text) and "汇总" in text:
            resolved = _resolve_columns(primary_sheet, ["部门", "金额"])
            operations = [
                NormalizeOperation(sheet=primary_ref, columns=[resolved["金额"]], target_type="number"),
                DeduplicateOperation(sheet=primary_ref, key_columns=[_resolve_columns(primary_sheet, ["编号"]).get("编号", resolved["部门"])]),
                GroupSummaryOperation(
                    sheet=primary_ref,
                    group_by=[resolved["部门"]],
                    metrics={resolved["金额"]: ["sum"]},
                    output_sheet="汇总结果",
                ),
                CreateIssueSheetOperation(output_sheet="问题清单"),
            ]
            return OperationPlan(
                id=plan_id,
                source_sheets=[primary_ref],
                operations=operations,
                outputs=["清洗后数据", "汇总结果", "问题清单"],
                explanation="统一金额格式并按订单号去重后汇总部门金额，并记录问题清单",
                requires_confirmation=True,
            )

        # Pattern 2: dedup + issue list
        if "去重" in text or "重复" in text:
            try:
                resolved = _resolve_columns(primary_sheet, ["编号"])
            except AmbiguousRequestError:
                resolved = {"编号": primary_sheet.columns[0].name} if primary_sheet.columns else {}
            operations = [
                DeduplicateOperation(sheet=primary_ref, key_columns=[resolved["编号"]]),
                CreateIssueSheetOperation(output_sheet="问题清单"),
            ]
            return OperationPlan(
                id=plan_id,
                source_sheets=[primary_ref],
                operations=operations,
                outputs=["清洗后数据", "问题清单"],
                explanation="按编号去重并记录问题清单",
                requires_confirmation=True,
            )

        # Pattern 3: filter by status
        if "筛选" in text or "过滤" in text:
            try:
                resolved = _resolve_columns(primary_sheet, ["状态"])
            except AmbiguousRequestError:
                raise AmbiguousRequestError("筛选任务需要状态列")
            operations = [
                FilterOperation(
                    sheet=primary_ref,
                    conditions=[FilterCondition(column=resolved["状态"], operator="not_null")],
                    match="all",
                    output_sheet="筛选结果",
                ),
            ]
            return OperationPlan(
                id=plan_id,
                source_sheets=[primary_ref],
                operations=operations,
                outputs=["清洗后数据", "筛选结果"],
                explanation="筛选状态列非空的记录",
                requires_confirmation=False,
            )

        # Pattern 4: fill formula
        if "公式" in text or "补" in normalized:
            try:
                resolved = _resolve_columns(primary_sheet, ["金额"])
            except AmbiguousRequestError:
                raise AmbiguousRequestError("补公式任务需要金额列")
            operations = [
                FillFormulaOperation(
                    sheet=primary_ref,
                    target_column=resolved["金额"],
                    expression=f"{{{resolved['金额']}}}*1",
                    start_row=2,
                    end_row=10_000,
                    only_blank=True,
                ),
            ]
            return OperationPlan(
                id=plan_id,
                source_sheets=[primary_ref],
                operations=operations,
                outputs=["清洗后数据"],
                explanation="在空白单元格中补充公式",
                requires_confirmation=True,
            )

        # Pattern 5: compare two sheets
        if "对比" in text or "比较" in text:
            sheets = []
            for idx, insp in enumerate(inspections):
                fid = f"file-{idx + 1:03d}"
                for sheet in insp.sheets:
                    sheets.append((fid, sheet))
            if len(sheets) < 2:
                raise AmbiguousRequestError("对比任务需要至少两个工作表")
            (fid1, s1), (fid2, s2) = sheets[0], sheets[1]
            ref1 = f"{fid1}::{s1.name}"
            ref2 = f"{fid2}::{s2.name}"
            try:
                resolved1 = _resolve_columns(s1, ["编号"])
                key = resolved1["编号"]
            except AmbiguousRequestError:
                key = s1.columns[0].name
            operations = [
                CompareOperation(
                    left_sheet=ref1,
                    right_sheet=ref2,
                    key_columns=[key],
                    output_sheet="对比结果",
                ),
            ]
            return OperationPlan(
                id=plan_id,
                source_sheets=[ref1, ref2],
                operations=operations,
                outputs=["对比结果"],
                explanation="按关键字段对比两侧变化",
                requires_confirmation=False,
            )

        # Fallback: explicit unrecognized request
        raise AmbiguousRequestError(
            "无法理解任务，请明确描述：检查/去重/筛选/补公式/对比 等关键词",
        )