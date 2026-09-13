import type {
  ExecutionView,
  PlanStepView,
  PlanView,
  SheetSummary,
} from "../domain/models";
import type {
  ConclusionDto,
  ExecutionResponse,
  FileUploadResponse,
  OperationPlanDto,
  SheetInspectionDto,
} from "./contracts";

const errorCodeMessages: Record<string, string> = {
  unsupported_file: "暂不支持该文件格式，请上传 xlsx、xls 或 csv。",
  file_too_large: "文件超过 25 MiB，请缩小文件后重试。",
  ambiguous_request: "任务中的字段或匹配方式不明确，请补充说明。",
  confirmation_required: "该操作会修改或删除数据，请确认影响范围后继续。",
  execution_failed: "文件处理失败，源文件未被修改，请调整任务后重试。",
  model_timeout: "智能规划暂时超时，请重试或切换演示模式。",
  network_error: "网络连接异常，请稍后重试。",
  request_timeout: "请求超时，请稍后重试。",
  invalid_plan: "规划结果无效，请调整任务后重试。",
  file_not_found: "文件已失效，请重新上传。",
  output_not_found: "输出文件已失效，请重新处理。",
};

export function mapErrorCodeToMessage(code: string, fallback: string): string {
  return errorCodeMessages[code] ?? fallback;
}

export function mapUploadResponse(resp: FileUploadResponse): {
  id: string;
  name: string;
  sizeBytes: number;
  sheets: SheetSummary[];
} {
  const sheets: SheetSummary[] = resp.inspection.sheets.map((s: SheetInspectionDto) => ({
    ref: `${resp.file_id}::${s.name}`,
    displayName: s.name,
    rowCount: s.row_count,
    columnCount: s.column_count,
    issues: s.issues.map((issue) => ({
      code: issue.code,
      severity: issue.severity,
      message: issue.message,
      column: issue.column ?? null,
      rows: issue.rows ?? [],
    })),
    columns: s.columns.map((c) => ({
      name: c.name,
      inferredType: c.inferred_type,
      nullCount: c.null_count,
      uniqueCount: c.unique_count,
    })),
  }));
  return {
    id: resp.file_id,
    name: resp.filename,
    sizeBytes: resp.size_bytes,
    sheets,
  };
}

function describeOperation(op: Record<string, unknown>): PlanStepView {
  const kind = op.kind as string;
  let description = kind;
  const columns: string[] = [];
  let outputSheet: string | null = null;
  if (kind === "normalize") {
    description = `标准化列 (${(op.columns as string[]).join(", ")})`;
    columns.push(...((op.columns as string[]) ?? []));
  } else if (kind === "deduplicate") {
    description = `按 ${(op.key_columns as string[]).join(", ")} 去重`;
    columns.push(...((op.key_columns as string[]) ?? []));
  } else if (kind === "filter") {
    description = "筛选记录";
    outputSheet = (op.output_sheet as string) ?? null;
  } else if (kind === "group_summary") {
    description = `按 ${(op.group_by as string[]).join(", ")} 汇总`;
    columns.push(...((op.group_by as string[]) ?? []));
    columns.push(...Object.keys((op.metrics as Record<string, unknown>) ?? {}));
    outputSheet = (op.output_sheet as string) ?? null;
  } else if (kind === "compare") {
    description = "对比两个工作表";
    columns.push(...((op.key_columns as string[]) ?? []));
    outputSheet = (op.output_sheet as string) ?? null;
  } else if (kind === "fill_formula") {
    description = "补充公式";
    if (op.target_column) columns.push(op.target_column as string);
  } else if (kind === "create_issue_sheet") {
    description = "生成问题清单";
    outputSheet = (op.output_sheet as string) ?? null;
  }
  return { kind, description, columns, outputSheet };
}

export function mapPlanResponse(plan: OperationPlanDto): PlanView {
  return {
    id: plan.id,
    explanation: plan.explanation,
    steps: (plan.operations as unknown as Record<string, unknown>[]).map(describeOperation),
    outputNames: plan.outputs,
    requiresConfirmation: plan.requires_confirmation,
  };
}

export function mapExecutionResponse(resp: ExecutionResponse): ExecutionView {
  return {
    outputId: resp.output_id,
    sheets: resp.sheets,
    metrics: resp.metrics as Record<string, string | number>,
    conclusions: resp.conclusions.map((c: ConclusionDto) => ({
      text: c.text,
      value: c.value,
      severity: c.severity,
      stepId: c.source.step_id,
    })),
  };
}