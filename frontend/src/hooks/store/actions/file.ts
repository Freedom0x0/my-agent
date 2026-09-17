import { ApiError, api } from "../../../api/httpClient";
import { makeUserFacingError, mapUploadResponse } from "../../../api/mappers";
import { parseWorkbook } from "../../useSpreadsheet";
import type { FileItem } from "../../../domain/workflow";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function fileActions(set: Set, get: Get): Pick<Actions, "uploadFile" | "removeFile" | "clearFileParseError"> {
  return {
    uploadFile: async (file: File) => {
      const { currentSessionId } = get();
      if (!currentSessionId) get().createSession();
      const sessionId = get().currentSessionId!;

      set({ status: "uploading", error: null });
      let uploaded: FileItem;
      try {
        const resp = await api.uploadFile(file);
        uploaded = mapUploadResponse(resp);
      } catch (err) {
        const e =
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, errorCode: "network_error", message: "上传失败" });
        set({ status: "error", error: makeUserFacingError(e.errorCode, e.message) });
        return;
      }
      set((s) => ({
        status: "parsing",
        files: [...s.files, uploaded],
      }));

      try {
        const buffer = await file.arrayBuffer();
        const preview = parseWorkbook(buffer, file.name);
        set((s) => ({
          status: "ready",
          filePreviews: { ...s.filePreviews, [uploaded.id]: preview },
        }));
      } catch (err) {
        const message = err instanceof Error ? err.message : "无法解析该文件";
        set((s) => ({
          status: "ready",
          fileParseErrors: { ...s.fileParseErrors, [uploaded.id]: message },
        }));
      }

      // Fill an existing empty tab if the user prepared one; otherwise add a new tab.
      const emptyTabId = (get().tabsBySession[sessionId] ?? []).find(
        (t) => t.kind === "file" && t.refId === "",
      )?.id;
      if (emptyTabId) {
        set((s) => ({
          tabsBySession: {
            ...s.tabsBySession,
            [sessionId]: (s.tabsBySession[sessionId] ?? []).map((t) =>
              t.id === emptyTabId ? { ...t, refId: uploaded.id, fileName: uploaded.name } : t,
            ),
          },
          activePreview: { kind: "file", fileId: uploaded.id },
        }));
      } else {
        get().addTab(sessionId, {
          kind: "file",
          refId: uploaded.id,
          fileName: uploaded.name,
        });
      }

      // file_ids are sent on the next chat message.
    },

    removeFile: (fileId: string) => {
      set((s) => {
        const { [fileId]: _preview, ...rest } = s.filePreviews;
        void _preview;
        const { [fileId]: _err, ...restErrors } = s.fileParseErrors;
        void _err;
        return {
          files: s.files.filter((f) => f.id !== fileId),
          filePreviews: rest,
          fileParseErrors: restErrors,
          ...(s.activePreview?.kind === "file" && s.activePreview.fileId === fileId
            ? { activePreview: null }
            : {}),
        };
      });
    },

    clearFileParseError: (fileId: string) => {
      set((s) => {
        const { [fileId]: _, ...rest } = s.fileParseErrors;
        void _;
        return { fileParseErrors: rest };
      });
    },
  };
}
