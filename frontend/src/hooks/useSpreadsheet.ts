import { useCallback, useState } from "react";
import * as XLSX from "xlsx";

import { MAX_PREVIEW_ROWS } from "../domain/models";
import type { PreviewSheet, WorkbookPreview } from "../domain/models";

const PARSE_ERROR_MESSAGE = "无法预览该文件格式";

export function parseWorkbook(
  buffer: ArrayBuffer,
  filename: string,
): WorkbookPreview {
  let workbook: XLSX.WorkBook;
  try {
    workbook = XLSX.read(buffer, { type: "array" });
  } catch {
    throw new Error(PARSE_ERROR_MESSAGE);
  }

  const sheets: PreviewSheet[] = (workbook.SheetNames ?? []).map((name) => {
    const worksheet = workbook.Sheets[name];
    const allRows = XLSX.utils.sheet_to_json<(string | number | boolean | null)[]>(
      worksheet,
      { header: 1, defval: "", blankrows: false, raw: false },
    );
    const totalRows = allRows.length;
    const sliced = allRows.slice(0, MAX_PREVIEW_ROWS);
    const rows = sliced.map((row) => row.map((cell) => (cell == null ? "" : String(cell))));
    return {
      name,
      rows,
      totalRows,
      truncated: totalRows > MAX_PREVIEW_ROWS,
    };
  });

  return { filename, sheets };
}

type ParseState =
  | { status: "idle" }
  | { status: "parsing" }
  | { status: "ready"; preview: WorkbookPreview }
  | { status: "error"; message: string };

export function useSpreadsheet() {
  const [state, setState] = useState<ParseState>({ status: "idle" });

  const parseFile = useCallback(async (file: File): Promise<WorkbookPreview | null> => {
    setState({ status: "parsing" });
    try {
      const buffer = await file.arrayBuffer();
      const preview = parseWorkbook(buffer, file.name);
      setState({ status: "ready", preview });
      return preview;
    } catch {
      setState({ status: "error", message: PARSE_ERROR_MESSAGE });
      return null;
    }
  }, []);

  const reset = useCallback(() => setState({ status: "idle" }), []);

  return { state, parseFile, reset } as const;
}
