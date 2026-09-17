import type {
  ChatMessage,
  ColumnSummary,
  FileItem,
  SheetSummary,
  ToolCallResult,
  UserFacingError,
} from "../domain/models";
import type {
  ChatResponse,
  FileUploadResponse,
  MessageDto,
  SheetInspectionDto,
  ToolCallResultDto,
} from "./contracts";

const errorCodeMessages: Record<string, string> = {
  unsupported_file: "暂不支持该文件格式，请上传 xlsx、xls 或 csv。",
  file_too_large: "文件超过 25 MiB，请缩小文件后重试。",
  ambiguous_request: "任务中的字段或匹配方式不明确，请补充说明。",
  confirmation_required: "该操作会修改或删除数据，请确认影响范围后继续。",
  execution_failed: "文件处理失败，源文件未被修改，请调整任务后重试。",
  model_timeout: "智能体暂时超时，请稍后重试。",
  model_error: "智能体响应异常，请稍后重试。",
  too_many_steps: "处理步骤过多，请精简需求。",
  model_truncated: "智能体输出过长，请简化需求。",
  invalid_request: "请求无效，请刷新页面后重试。",
  network_error: "无法连接到后端（请确认服务已启动，或检查浏览器控制台网络面板）。",
  request_timeout: "请求超时，请稍后重试。",
  file_not_found: "文件已失效，请重新上传。",
  output_not_found: "输出文件已失效，请重新处理。",
  http_error: "服务器响应异常，请稍后重试。",
};

export function mapErrorCodeToMessage(code: string, fallback: string): string {
  return errorCodeMessages[code] ?? fallback;
}

export function makeUserFacingError(
  errorCode: string,
  fallback: string,
): UserFacingError {
  return { errorCode, message: mapErrorCodeToMessage(errorCode, fallback) };
}

export function mapUploadResponse(resp: FileUploadResponse): FileItem {
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
    columns: s.columns.map(
      (c): ColumnSummary => ({
        name: c.name,
        inferredType: c.inferred_type,
        nullCount: c.null_count,
        uniqueCount: c.unique_count,
      }),
    ),
  }));
  return {
    id: resp.file_id,
    name: resp.filename,
    sizeBytes: resp.size_bytes,
    sheets,
  };
}

function mapToolCall(dto: ToolCallResultDto): ToolCallResult {
  return {
    tool: dto.tool,
    status: dto.status,
    summary: dto.summary,
    outputId: dto.output_id ?? null,
    outputName: dto.output_name ?? null,
  };
}

export function mapChatResponseToAssistantMessage(
  resp: ChatResponse,
  id: string,
): ChatMessage {
  return {
    id,
    role: "assistant",
    content: resp.reply,
    toolCalls: resp.tool_calls.map(mapToolCall),
    outputId: resp.output_id ?? null,
    outputName: resp.output_name ?? null,
    sheets: resp.sheets ?? [],
    timestamp: Date.now(),
  };
}

function extractText(content: MessageDto["content"]): string {
  if (typeof content === "string") return content;
  return content
    .filter((b): b is { type: string; text?: string } =>
      typeof b === "object" && b !== null && (b as { type?: unknown }).type === "text")
    .map((b) => b.text ?? "")
    .join("");
}

export function mapSessionMessages(
  raw: MessageDto[],
  sessionId?: string,
  baseIndex?: number,
): ChatMessage[] {
  return raw.map((m, idx) => {
    const outId = (m.tool_calls ?? []).reduce<string | null>(
      (acc, t) => t.output_id ?? acc,
      null,
    );
    const outName = (m.tool_calls ?? []).reduce<string | null>(
      (acc, t) => t.output_name ?? acc,
      null,
    );
    const position = (baseIndex ?? 0) + idx;
    const id = sessionId ? `${sessionId}-${position}` : `loaded-${position}`;
    return {
      id,
      role: m.role,
      content: extractText(m.content),
      toolCalls: m.tool_calls?.map(mapToolCall),
      outputId: outId,
      outputName: outName,
      sheets: [],
      timestamp: Date.now(),
    };
  });
}
