import { useState } from "react";

import { SheetTabs } from "./SheetTabs";
import { MAX_PREVIEW_ROWS } from "../domain/models";
import type { WorkbookPreview } from "../domain/models";

type Props = {
  preview: WorkbookPreview | null;
  error?: string | null;
  loading?: boolean;
  emptyMessage?: string;
  activeSheet?: string | null;
  onSheetChange?: (sheet: string) => void;
  onDownload?: () => void;
};

export function SpreadsheetPreview({
  preview,
  error,
  loading,
  emptyMessage,
  activeSheet: controlledSheet,
  onSheetChange,
  onDownload,
}: Props) {
  const [internalSheet, setInternalSheet] = useState<string | null>(
    preview?.sheets[0]?.name ?? null,
  );

  const isControlled = controlledSheet !== undefined;
  const activeSheet = isControlled ? controlledSheet : internalSheet;
  const setSheet = (name: string) => {
    if (isControlled) onSheetChange?.(name);
    else setInternalSheet(name);
  };

  if (error) {
    return (
      <div className="preview-empty" data-testid="spreadsheet-preview">
        <p className="empty-state">{error}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="preview-skeleton" data-testid="spreadsheet-preview">
        <div className="skeleton-row" />
        <div className="skeleton-row" />
        <div className="skeleton-row" />
      </div>
    );
  }

  if (!preview || preview.sheets.length === 0) {
    return (
      <div className="preview-empty" data-testid="spreadsheet-preview">
        <p className="empty-state">{emptyMessage ?? "尚未上传文件"}</p>
      </div>
    );
  }

  const sheet =
    preview.sheets.find((s) => s.name === activeSheet) ?? preview.sheets[0];

  return (
    <div className="preview" data-testid="spreadsheet-preview">
      <SheetTabs
        sheets={preview.sheets.map((s) => s.name)}
        active={sheet.name}
        onSelect={setSheet}
        onDownload={onDownload}
      />
      <TableView sheet={sheet} />
    </div>
  );
}

function TableView({ sheet }: { sheet: WorkbookPreview["sheets"][number] }) {
  const colCount = sheet.rows[0]?.length ?? 0;
  const columns = Array.from({ length: Math.max(colCount, 1) }, (_, i) => `列 ${i + 1}`);
  return (
    <div className="preview-table-wrapper">
      <table className="preview-table">
        <thead>
          <tr>
            <th className="row-index" scope="col">#</th>
            {columns.map((label, idx) => (
              <th key={idx} scope="col">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sheet.rows.map((row, rowIdx) => (
            <tr key={rowIdx}>
              <td className="row-index">{rowIdx + 1}</td>
              {columns.map((_, colIdx) => (
                <td key={colIdx}>{row[colIdx] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {sheet.truncated && (
        <p className="preview-note">
          仅显示前 {MAX_PREVIEW_ROWS} 行（共计 {sheet.totalRows} 行）
        </p>
      )}
    </div>
  );
}
