import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import { App } from "../App";
import { api } from "../api/httpClient";

vi.mock("../api/httpClient", async () => {
  const actual = await vi.importActual<typeof import("../api/httpClient")>(
    "../api/httpClient",
  );
  return {
    ...actual,
    api: {
      uploadFile: vi.fn(),
      createPlan: vi.fn(),
      executePlan: vi.fn(),
      downloadUrl: vi.fn((id: string) => `/api/outputs/${id}`),
      getAudit: vi.fn(),
    },
  };
});

const mockedApi = api as unknown as {
  uploadFile: ReturnType<typeof vi.fn>;
  createPlan: ReturnType<typeof vi.fn>;
  executePlan: ReturnType<typeof vi.fn>;
  downloadUrl: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("App workflow", () => {
  it("renders upload, plan and result panels in sequence", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce({
      file_id: "f-1",
      filename: "sample.xlsx",
      size_bytes: 1024,
      inspection: {
        filename: "sample.xlsx",
        file_type: "xlsx",
        sheets: [
          {
            name: "明细",
            row_count: 3,
            column_count: 3,
            columns: [
              { name: "部门", inferred_type: "text", null_count: 0, unique_count: 2, sample_values: [] },
              { name: "金额", inferred_type: "number", null_count: 0, unique_count: 3, sample_values: [] },
            ],
            preview: [],
            issues: [
              {
                code: "duplicate_rows",
                severity: "warning",
                message: "检测到重复",
                sheet: "明细",
                column: null,
                rows: [2],
              },
            ],
            formula_count: 0,
          },
        ],
      },
    });
    mockedApi.createPlan.mockResolvedValueOnce({
      plan: {
        id: "plan-1",
        source_sheets: ["f-1::明细"],
        operations: [
          { kind: "normalize", sheet: "f-1::明细", columns: ["金额"], target_type: "number" },
          { kind: "deduplicate", sheet: "f-1::明细", key_columns: ["订单号"], keep: "first" },
          { kind: "group_summary", sheet: "f-1::明细", group_by: ["部门"], metrics: { 金额: ["sum"] }, output_sheet: "汇总结果" },
          { kind: "create_issue_sheet", output_sheet: "问题清单", issue_codes: null },
        ],
        outputs: ["清洗后数据", "汇总结果", "问题清单"],
        explanation: "测试计划",
        clarification_question: null,
        requires_confirmation: true,
      },
    });
    mockedApi.executePlan.mockResolvedValueOnce({
      output_id: "out-1",
      sheets: ["清洗后数据", "汇总结果", "问题清单", "_audit"],
      metrics: { input_rows: 3, output_rows: 3, issues_count: 1 },
      conclusions: [
        {
          text: "去重删除 1 行",
          value: 1,
          severity: "info",
          source: { step_id: "step-002", sheet: "明细", columns: [], condition: null, formula: null, rows: [] },
        },
      ],
      audit_events: [
        {
          step_id: "step-002",
          operation: "deduplicate",
          input_sheets: ["f-1::明细"],
          output_sheets: ["清洗后数据"],
          columns: ["订单号"],
          input_rows: 3,
          output_rows: 2,
          affected_rows: [2],
          details: {},
        },
      ],
    });

    render(<App />);

    const file = new File(["hello"], "sample.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(screen.getByTestId("file-item")).toBeInTheDocument());
    expect(screen.getByTestId("inspection-sheet")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("task-input"), {
      target: { value: "检查并汇总" },
    });
    fireEvent.click(screen.getByTestId("plan-button"));

    await waitFor(() => expect(screen.getByTestId("plan-panel")).toBeInTheDocument());
    expect(screen.getByTestId("confirmation-warning")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("execute-button"));
    fireEvent.click(screen.getByTestId("execute-button"));

    await waitFor(() => expect(screen.getByTestId("result-panel")).toBeInTheDocument());
    expect(screen.getByTestId("conclusion-list").textContent).toContain("去重");
    expect(screen.getByTestId("download-link")).toHaveAttribute("href", "/api/outputs/out-1");
    expect(mockedApi.executePlan).toHaveBeenCalledWith(
      ["f-1"],
      expect.objectContaining({ id: "plan-1" }),
      "confirm:plan-1",
    );
  });

  it("surfaces user friendly error when upload fails", async () => {
    const { ApiError } = await import("../api/httpClient");
    mockedApi.uploadFile.mockRejectedValueOnce(
      new ApiError({
        status: 400,
        errorCode: "unsupported_file",
        message: "raw message",
      }),
    );

    render(<App />);
    const file = new File(["x"], "note.txt", { type: "text/plain" });
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(screen.getByTestId("app-error")).toBeInTheDocument());
    expect(screen.getByTestId("app-error").textContent).toContain("暂不支持");
  });
});