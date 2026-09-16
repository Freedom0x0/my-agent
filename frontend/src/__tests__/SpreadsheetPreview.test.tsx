import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { SpreadsheetPreview } from "../components/SpreadsheetPreview";
import type { WorkbookPreview } from "../domain/models";

const samplePreview: WorkbookPreview = {
  filename: "demo.xlsx",
  sheets: [
    {
      name: "明细",
      rows: [
        ["部门", "金额"],
        ["销售", "100"],
        ["市场", "200"],
      ],
      totalRows: 3,
      truncated: false,
    },
    {
      name: "汇总",
      rows: [["部门", "总金额"]],
      totalRows: 1,
      truncated: false,
    },
  ],
};

describe("SpreadsheetPreview", () => {
  it("renders the active sheet rows", () => {
    render(<SpreadsheetPreview preview={samplePreview} />);
    expect(screen.getByTestId("spreadsheet-preview")).toBeInTheDocument();
    // First sheet is active by default.
    expect(screen.getByText("销售")).toBeInTheDocument();
  });

  it("renders sheet tabs and switches the active sheet on click", () => {
    render(<SpreadsheetPreview preview={samplePreview} />);
    const tabs = screen.getAllByTestId("sheet-tab");
    expect(tabs.length).toBe(2);

    fireEvent.click(tabs[1]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("总金额")).toBeInTheDocument();
  });

  it("renders empty state when no preview provided", () => {
    render(<SpreadsheetPreview preview={null} />);
    expect(screen.getByText("尚未上传文件")).toBeInTheDocument();
  });

  it("renders error message when error prop is set", () => {
    render(<SpreadsheetPreview preview={null} error="无法预览该文件格式" />);
    expect(screen.getByText("无法预览该文件格式")).toBeInTheDocument();
  });
});
