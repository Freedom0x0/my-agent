"""Operation DSL validation and confirmation policy."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..schemas import (
    CompareOperation,
    CreateIssueSheetOperation,
    DeduplicateOperation,
    FillFormulaOperation,
    FilterOperation,
    GroupSummaryOperation,
    NormalizeOperation,
    Operation,
    OperationPlan,
)

HIGH_IMPACT_KINDS = {"deduplicate", "fill_formula"}

OUTPUT_NAME_MAX_LEN = 31
RESERVED_SHEET_NAMES = {"_audit"}

ALLOWED_AGG_FUNCS = {"sum", "mean", "count", "min", "max"}
ALLOWED_OPERATORS = {
    "eq", "ne", "contains", "gt", "gte", "lt", "lte",
    "is_null", "not_null", "in",
}


class InvalidPlanError(ValueError):
    """Plan validation failed; API maps this to `invalid_plan`."""


class ConfirmationRequired(Exception):
    """Raised when a high-impact plan is executed without a valid token."""

    def __init__(self, plan_id: str, affected_rows: list[int]):
        super().__init__(f"plan {plan_id} requires confirmation")
        self.plan_id = plan_id
        self.affected_rows = affected_rows


def expected_confirmation_token(plan_id: str) -> str:
    return f"confirm:{plan_id}"


def _normalize_output_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise InvalidPlanError("输出工作表名称不能为空")
    if cleaned in RESERVED_SHEET_NAMES:
        raise InvalidPlanError(f"输出工作表名称不能使用保留名 {cleaned}")
    if len(cleaned) > OUTPUT_NAME_MAX_LEN:
        raise InvalidPlanError(
            f"输出工作表名称 {cleaned} 超过 {OUTPUT_NAME_MAX_LEN} 个字符",
        )
    return cleaned


def validate_plan(plan: OperationPlan, sheet_columns: dict[str, set[str]]) -> None:
    """Validate plan structure against the available sheets and columns.

    `sheet_columns` maps SheetRef (`<file_id>::<sheet>`) to a set of column names.
    """
    if not plan.operations:
        raise InvalidPlanError("计划至少包含一个操作")

    seen_outputs: set[str] = set()
    has_transform = False
    has_create_issue = False

    for sheet_ref in plan.source_sheets:
        if sheet_ref not in sheet_columns:
            raise InvalidPlanError(f"工作表 {sheet_ref} 不存在")

    for op in plan.operations:
        kind = op.kind
        if kind in ("normalize", "deduplicate", "filter", "group_summary", "fill_formula"):
            sheet_ref = getattr(op, "sheet")
            if sheet_ref not in sheet_columns:
                raise InvalidPlanError(f"工作表 {sheet_ref} 不存在")
        if kind == "compare":
            for s in (op.left_sheet, op.right_sheet):
                if s not in sheet_columns:
                    raise InvalidPlanError(f"工作表 {s} 不存在")

        if isinstance(op, NormalizeOperation):
            for col in op.columns:
                if col not in sheet_columns[op.sheet]:
                    raise InvalidPlanError(f"列 {col} 不存在于工作表 {op.sheet}")
            has_transform = True

        elif isinstance(op, DeduplicateOperation):
            for col in op.key_columns:
                if col not in sheet_columns[op.sheet]:
                    raise InvalidPlanError(f"列 {col} 不存在于工作表 {op.sheet}")
            has_transform = True

        elif isinstance(op, FilterOperation):
            for cond in op.conditions:
                if cond.column not in sheet_columns[op.sheet]:
                    raise InvalidPlanError(f"列 {cond.column} 不存在于工作表 {op.sheet}")
                if cond.operator not in ALLOWED_OPERATORS:
                    raise InvalidPlanError(f"不支持的筛选操作符 {cond.operator}")
            name = _normalize_output_name(op.output_sheet)
            if name in seen_outputs:
                raise InvalidPlanError(f"输出工作表名称重复 {name}")
            seen_outputs.add(name)

        elif isinstance(op, GroupSummaryOperation):
            for col in op.group_by:
                if col not in sheet_columns[op.sheet]:
                    raise InvalidPlanError(f"列 {col} 不存在于工作表 {op.sheet}")
            for col, funcs in op.metrics.items():
                if col not in sheet_columns[op.sheet]:
                    raise InvalidPlanError(f"列 {col} 不存在于工作表 {op.sheet}")
                for fn in funcs:
                    if fn not in ALLOWED_AGG_FUNCS:
                        raise InvalidPlanError(f"不支持的聚合函数 {fn}")
            name = _normalize_output_name(op.output_sheet)
            if name in seen_outputs:
                raise InvalidPlanError(f"输出工作表名称重复 {name}")
            seen_outputs.add(name)

        elif isinstance(op, CompareOperation):
            for col in op.key_columns:
                if col not in sheet_columns[op.left_sheet]:
                    raise InvalidPlanError(f"列 {col} 不存在于左工作表 {op.left_sheet}")
                if col not in sheet_columns[op.right_sheet]:
                    raise InvalidPlanError(f"列 {col} 不存在于右工作表 {op.right_sheet}")
            name = _normalize_output_name(op.output_sheet)
            if name in seen_outputs:
                raise InvalidPlanError(f"输出工作表名称重复 {name}")
            seen_outputs.add(name)

        elif isinstance(op, FillFormulaOperation):
            if op.target_column not in sheet_columns[op.sheet]:
                raise InvalidPlanError(
                    f"列 {op.target_column} 不存在于工作表 {op.sheet}",
                )
            if op.start_row > op.end_row:
                raise InvalidPlanError("公式范围起始行不能大于结束行")

        elif isinstance(op, CreateIssueSheetOperation):
            name = _normalize_output_name(op.output_sheet)
            if name in seen_outputs:
                raise InvalidPlanError(f"输出工作表名称重复 {name}")
            seen_outputs.add(name)
            has_create_issue = True

        else:
            raise InvalidPlanError(f"未知操作类型 {kind}")

    # The plan.outputs must include the names declared by operations
    declared_outputs: set[str] = set()
    for op in plan.operations:
        if isinstance(op, (FilterOperation, GroupSummaryOperation, CompareOperation, CreateIssueSheetOperation)):
            declared_outputs.add(op.output_sheet)
    missing = declared_outputs - set(plan.outputs)
    if missing:
        raise InvalidPlanError(
            f"计划 outputs 缺少操作声明的输出: {', '.join(sorted(missing))}",
        )

    # Transform pipeline requires a sink output
    if has_transform and "清洗后数据" not in plan.outputs and len(plan.outputs) < 1:
        raise InvalidPlanError("包含变换操作的计划必须声明至少一个输出")


def requires_confirmation(plan: OperationPlan) -> bool:
    return any(op.kind in HIGH_IMPACT_KINDS for op in plan.operations)


def normalize_plan(plan: OperationPlan) -> OperationPlan:
    """Recompute the derived `requires_confirmation` field from the operations."""
    return plan.model_copy(update={"requires_confirmation": requires_confirmation(plan)})