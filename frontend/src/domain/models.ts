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

export type ToolCallResult = {
  tool: string;
  status: "ok" | "error";
  summary: string;
  outputId?: string | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallResult[];
  outputId?: string | null;
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
