export type AppStatus =
  | "idle"
  | "uploading"
  | "parsing"
  | "ready"
  | "processing"
  | "completed"
  | "error";

export type IssueSummary = {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  column: string | null;
  rows: number[];
};

export type ColumnSummary = {
  name: string;
  inferredType: string;
  nullCount: number;
  uniqueCount: number;
};

export type SheetSummary = {
  ref: string;
  displayName: string;
  rowCount: number;
  columnCount: number;
  issues: IssueSummary[];
  columns: ColumnSummary[];
};

export type FileItem = {
  id: string;
  name: string;
  sizeBytes: number;
  sheets: SheetSummary[];
};

export type PreviewSheet = {
  name: string;
  rows: string[][]; // up to 500 rows
  totalRows: number; // original row count
  truncated: boolean;
};

export type WorkbookPreview = {
  filename: string;
  sheets: PreviewSheet[];
};

/** `running` only ever exists on the client — a persisted tool call is always ok/error. */
export type ToolStatus = "running" | "ok" | "error";

export type ToolCallResult = {
  tool: string;
  status: ToolStatus;
  summary: string;
  /** tool_use id from the model — how `tool_end` finds its `tool_start`. */
  id?: string;
  outputId?: string | null;
  outputName?: string | null;
};

export type Segment =
  | { type: "text"; content: string }
  | { type: "tool"; call: ToolCallResult; outputName?: string | null };

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallResult[];
  segments?: Segment[];
  /** True while this message is still being streamed; cleared when the turn ends. */
  streaming?: boolean;
  outputId?: string | null;
  outputName?: string | null;
  sheets?: string[];
  timestamp: number;
};

export type UserFacingError = {
  errorCode: string;
  message: string;
};

export const MAX_PREVIEW_ROWS = 500;
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = [".xlsx", ".xls", ".csv"] as const;
export const MAX_MESSAGE_LENGTH = 1000;
