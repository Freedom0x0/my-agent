import { ApiError, api } from "../../../api/httpClient";
import { makeUserFacingError, mapUploadResponse } from "../../../api/mappers";
import { parseWorkbook } from "../../useSpreadsheet";
import type { FileItem, WorkbookPreview } from "../../../domain/workflow";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function fileActions(set: Set, get: Get): Pick<Actions, "uploadFile" | "removeFile"> {
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

      // Client-side preview (non-blocking failure).
      let preview: WorkbookPreview | null = null;
      try {
        const buffer = await file.arrayBuffer();
        preview = parseWorkbook(buffer, file.name);
        set((s) => ({
          status: "ready",
          filePreviews: { ...s.filePreviews, [uploaded.id]: preview! },
        }));
      } catch {
        set({ status: "ready" });
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
        const { [fileId]: _, ...rest } = s.filePreviews;
        void _;
        return {
          files: s.files.filter((f) => f.id !== fileId),
          filePreviews: rest,
          ...(s.activePreview?.kind === "file" && s.activePreview.fileId === fileId
            ? { activePreview: null }
            : {}),
        };
      });
    },
  };
}
