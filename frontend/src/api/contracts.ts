import { z } from "zod";

export const errorResponseSchema = z.object({
  error_code: z.string(),
  message: z.string(),
  details: z.record(z.unknown()).optional(),
});

// --- Sessions ---

export const sessionSummarySchema = z.object({
  session_id: z.string(),
  title: z.string(),
  updated_at: z.string(),
  message_count: z.number(),
  last_user_msg: z.string(),
});

export type SessionSummary = z.infer<typeof sessionSummarySchema>;

export const sessionListResponseSchema = z.object({
  sessions: z.array(sessionSummarySchema),
});

// --- Chat ---

export const toolCallResultDtoSchema = z.object({
  tool: z.string(),
  status: z.enum(["ok", "error"]),
  summary: z.string(),
  output_id: z.string().nullable().optional(),
});

export const messageDtoSchema = z.object({
  role: z.enum(["user", "assistant"]),
  // backend stores assistant content as either a string or content_blocks list
  content: z.union([z.string(), z.array(z.record(z.unknown()))]),
  tool_calls: z.array(toolCallResultDtoSchema).optional(),
});

export const sessionDetailSchema = z.object({
  session_id: z.string(),
  title: z.string(),
  updated_at: z.string(),
  message_count: z.number(),
  last_user_msg: z.string(),
  messages: z.array(messageDtoSchema),
  output_ids: z.array(z.string()),
});

export const chatRequestSchema = z.object({
  message: z.string().min(1).max(4000),
  file_ids: z.array(z.string()),
  session_id: z.string().optional(),
});

export const chatResponseSchema = z.object({
  reply: z.string(),
  tool_calls: z.array(toolCallResultDtoSchema),
  output_id: z.string().nullable().optional(),
  sheets: z.array(z.string()).optional(),
  session_id: z.string().optional(),
  error_code: z.string().nullable().optional(),
});

// --- Inspection ---

export const issueSchema = z.object({
  code: z.string(),
  severity: z.enum(["info", "warning", "error"]),
  message: z.string(),
  sheet: z.string(),
  column: z.string().nullable().optional(),
  rows: z.array(z.number()).optional(),
});

export const columnInspectionDtoSchema = z.object({
  name: z.string(),
  inferred_type: z.enum(["text", "number", "date", "boolean", "mixed", "empty"]),
  null_count: z.number(),
  unique_count: z.number(),
  sample_values: z.array(z.string()),
});

export const sheetInspectionDtoSchema = z.object({
  name: z.string(),
  row_count: z.number(),
  column_count: z.number(),
  columns: z.array(columnInspectionDtoSchema),
  preview: z.array(z.record(z.unknown())),
  issues: z.array(issueSchema),
  formula_count: z.number(),
});

export const workbookInspectionDtoSchema = z.object({
  filename: z.string(),
  file_type: z.enum(["xlsx", "xls", "csv"]),
  sheets: z.array(sheetInspectionDtoSchema),
});

export const fileUploadResponseSchema = z.object({
  file_id: z.string(),
  filename: z.string(),
  size_bytes: z.number(),
  inspection: workbookInspectionDtoSchema,
});

export type FileUploadResponse = z.infer<typeof fileUploadResponseSchema>;
export type ToolCallResultDto = z.infer<typeof toolCallResultDtoSchema>;
export type MessageDto = z.infer<typeof messageDtoSchema>;
export type SessionDetail = z.infer<typeof sessionDetailSchema>;
export type ChatRequest = z.infer<typeof chatRequestSchema>;
export type ChatResponse = z.infer<typeof chatResponseSchema>;
export type ErrorResponse = z.infer<typeof errorResponseSchema>;
export type WorkbookInspectionDto = z.infer<typeof workbookInspectionDtoSchema>;
export type SheetInspectionDto = z.infer<typeof sheetInspectionDtoSchema>;