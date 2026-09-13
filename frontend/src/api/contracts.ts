import { z } from "zod";

export const errorResponseSchema = z.object({
  error_code: z.string(),
  message: z.string(),
  details: z.record(z.unknown()).optional(),
});

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

export const operationSchema = z.object({
  kind: z.string(),
});

export const operationPlanDtoSchema = z.object({
  id: z.string(),
  source_sheets: z.array(z.string()),
  operations: z.array(operationSchema),
  outputs: z.array(z.string()),
  explanation: z.string(),
  clarification_question: z.string().nullable().optional(),
  requires_confirmation: z.boolean(),
});

export const planResponseSchema = z.object({
  plan: operationPlanDtoSchema,
});

export const conclusionDtoSchema = z.object({
  text: z.string(),
  value: z.union([z.string(), z.number(), z.null()]),
  severity: z.enum(["info", "warning", "error"]),
  source: z.object({
    step_id: z.string(),
    sheet: z.string(),
    columns: z.array(z.string()),
    condition: z.string().nullable().optional(),
    formula: z.string().nullable().optional(),
    rows: z.array(z.number()),
  }),
});

export const auditEventDtoSchema = z.object({
  step_id: z.string(),
  operation: z.string(),
  input_sheets: z.array(z.string()),
  output_sheets: z.array(z.string()),
  columns: z.array(z.string()),
  input_rows: z.number(),
  output_rows: z.number(),
  affected_rows: z.array(z.number()),
  details: z.record(z.unknown()),
});

export const executionResponseSchema = z.object({
  output_id: z.string(),
  sheets: z.array(z.string()),
  metrics: z.record(z.union([z.string(), z.number()])),
  conclusions: z.array(conclusionDtoSchema),
  audit_events: z.array(auditEventDtoSchema),
});

export const auditResponseSchema = z.object({
  output_id: z.string(),
  events: z.array(auditEventDtoSchema),
  conclusions: z.array(conclusionDtoSchema),
});

export type FileUploadResponse = z.infer<typeof fileUploadResponseSchema>;
export type OperationPlanDto = z.infer<typeof operationPlanDtoSchema>;
export type PlanResponse = z.infer<typeof planResponseSchema>;
export type ExecutionResponse = z.infer<typeof executionResponseSchema>;
export type AuditResponse = z.infer<typeof auditResponseSchema>;
export type ErrorResponse = z.infer<typeof errorResponseSchema>;
export type WorkbookInspectionDto = z.infer<typeof workbookInspectionDtoSchema>;
export type SheetInspectionDto = z.infer<typeof sheetInspectionDtoSchema>;
export type ConclusionDto = z.infer<typeof conclusionDtoSchema>;