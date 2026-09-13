from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    mode: str


# --- Inspection models ---

class ColumnInspection(BaseModel):
    name: str
    inferred_type: Literal["text", "number", "date", "boolean", "mixed", "empty"]
    null_count: int
    unique_count: int
    sample_values: list[str] = Field(default_factory=list, max_length=5)


class DataIssue(BaseModel):
    code: Literal[
        "blank_header",
        "null_values",
        "duplicate_rows",
        "mixed_numeric",
        "mixed_date",
        "empty_sheet",
        "reserved_column",
    ]
    severity: Literal["info", "warning", "error"]
    message: str
    sheet: str
    column: str | None = None
    rows: list[int] = Field(default_factory=list, max_length=200)


class SheetInspection(BaseModel):
    name: str
    row_count: int
    column_count: int
    columns: list[ColumnInspection]
    preview: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    issues: list[DataIssue] = Field(default_factory=list)
    formula_count: int = 0


class WorkbookInspection(BaseModel):
    filename: str
    file_type: Literal["xlsx", "xls", "csv"]
    sheets: list[SheetInspection]


class SheetRef(BaseModel):
    file_id: str
    sheet_name: str
    ref: str  # exactly "<file_id>::<sheet_name>"


# --- Operation models (discriminated by `kind`) ---

class NormalizeOperation(BaseModel):
    kind: Literal["normalize"] = "normalize"
    sheet: str
    columns: list[str] = Field(min_length=1)
    target_type: Literal["number", "date", "text"]


class DeduplicateOperation(BaseModel):
    kind: Literal["deduplicate"] = "deduplicate"
    sheet: str
    key_columns: list[str] = Field(min_length=1)
    keep: Literal["first", "last"] = "first"


class FilterCondition(BaseModel):
    column: str
    operator: Literal[
        "eq", "ne", "contains", "gt", "gte", "lt", "lte",
        "is_null", "not_null", "in",
    ]
    value: str | int | float | bool | list[str | int | float] | None = None


class FilterOperation(BaseModel):
    kind: Literal["filter"] = "filter"
    sheet: str
    conditions: list[FilterCondition] = Field(min_length=1)
    match: Literal["all", "any"] = "all"
    output_sheet: str = "筛选结果"


class GroupSummaryOperation(BaseModel):
    kind: Literal["group_summary"] = "group_summary"
    sheet: str
    group_by: list[str] = Field(min_length=1)
    metrics: dict[str, list[Literal["sum", "mean", "count", "min", "max"]]]
    output_sheet: str = "汇总结果"


class CompareOperation(BaseModel):
    kind: Literal["compare"] = "compare"
    left_sheet: str
    right_sheet: str
    key_columns: list[str] = Field(min_length=1)
    compare_columns: list[str] | None = None
    output_sheet: str = "对比结果"


class FillFormulaOperation(BaseModel):
    kind: Literal["fill_formula"] = "fill_formula"
    sheet: str
    target_column: str
    expression: str
    start_row: int = Field(ge=2)
    end_row: int = Field(ge=2)
    only_blank: bool = True


class CreateIssueSheetOperation(BaseModel):
    kind: Literal["create_issue_sheet"] = "create_issue_sheet"
    output_sheet: str = "问题清单"
    issue_codes: list[str] | None = None


Operation = Annotated[
    NormalizeOperation
    | DeduplicateOperation
    | FilterOperation
    | GroupSummaryOperation
    | CompareOperation
    | FillFormulaOperation
    | CreateIssueSheetOperation,
    Field(discriminator="kind"),
]


class OperationPlan(BaseModel):
    id: str
    source_sheets: list[str] = Field(min_length=1)
    operations: list[Operation] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    explanation: str
    clarification_question: str | None = None
    requires_confirmation: bool = False


# --- Execution / audit models ---

class AuditEvent(BaseModel):
    step_id: str
    operation: str
    input_sheets: list[str]
    output_sheets: list[str]
    columns: list[str] = Field(default_factory=list)
    input_rows: int
    output_rows: int
    affected_rows: list[int] = Field(default_factory=list, max_length=200)
    details: dict[str, Any] = Field(default_factory=dict)


class ConclusionSource(BaseModel):
    step_id: str
    sheet: str
    columns: list[str] = Field(default_factory=list)
    condition: str | None = None
    formula: str | None = None
    rows: list[int] = Field(default_factory=list, max_length=200)


class Conclusion(BaseModel):
    text: str
    value: str | int | float | None = None
    severity: Literal["info", "warning", "error"] = "info"
    source: ConclusionSource


class ExecutionResult(BaseModel):
    output_id: str
    output_path: str
    sheets: list[str]
    metrics: dict[str, str | int | float]
    conclusions: list[Conclusion]
    audit_events: list[AuditEvent]


# --- API models ---

class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    inspection: WorkbookInspection


class PlanResponse(BaseModel):
    plan: OperationPlan


class ExecuteRequest(BaseModel):
    file_ids: list[str] = Field(min_length=1)
    plan: OperationPlan
    confirmation_token: str | None = None


class ExecutionResponse(BaseModel):
    output_id: str
    sheets: list[str]
    metrics: dict[str, str | int | float]
    conclusions: list[Conclusion]
    audit_events: list[AuditEvent]


class AuditResponse(BaseModel):
    output_id: str
    events: list[AuditEvent]
    conclusions: list[Conclusion]


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)