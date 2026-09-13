export type WorkflowStatus =
  | "idle"
  | "uploading"
  | "inspected"
  | "planning"
  | "plan_ready"
  | "executing"
  | "completed"
  | "error";

export type FileItem = {
  id: string;
  name: string;
  sizeBytes: number;
  sheets: SheetSummary[];
};

export type IssueSummary = {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  column: string | null;
  rows: number[];
};

export type SheetSummary = {
  ref: string;
  displayName: string;
  rowCount: number;
  columnCount: number;
  issues: IssueSummary[];
  columns: { name: string; inferredType: string; nullCount: number; uniqueCount: number }[];
};

export type PlanStepView = {
  kind: string;
  description: string;
  columns: string[];
  outputSheet: string | null;
};

export type PlanView = {
  id: string;
  explanation: string;
  steps: PlanStepView[];
  outputNames: string[];
  requiresConfirmation: boolean;
};

export type ConclusionView = {
  text: string;
  value: string | number | null;
  severity: "info" | "warning" | "error";
  stepId: string;
};

export type ExecutionView = {
  outputId: string;
  sheets: string[];
  metrics: Record<string, string | number>;
  conclusions: ConclusionView[];
};

export type UserFacingError = {
  errorCode: string;
  message: string;
};