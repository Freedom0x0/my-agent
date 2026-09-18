import { ApiError, api } from "../../../api/httpClient";
import { makeUserFacingError, mapUploadResponse } from "../../../api/mappers";
import { parseWorkbook } from "../../useSpreadsheet";
import type { FileItem } from "../../../domain/workflow";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

/**
 * Preview fetches already in flight, keyed by refId. Module-level rather than store
 * state: it's de-duplication bookkeeping, nothing renders it.
 */
const inflight = new Map<string, Promise<void>>();

export function fileActions(
  set: Set,
  get: Get,
): Pick<Actions, "uploadFile" | "removeFile" | "ensurePreview"> {
  return {
    uploadFile: async (file: File) => {
      const { currentSessionId } = get();
      if (!currentSessionId) get().createSession();
      const sessionId = get().currentSessionId!;

      set({ status: "uploading", error: null });
      let uploaded: FileItem;
      try {
        const resp = await api.uploadFile(file, sessionId);
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

      // Parse the local File directly — the bytes are already in hand, no round trip.
      // This seeds the same cache `ensurePreview` fills, so the tab below is ready.
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
          previewErrors: { ...s.previewErrors, [uploaded.id]: message },
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

    /**
     * Make sure a tab has its parsed preview, fetching it on demand.
     *
     * This is the only thing that fills the preview caches outside of a fresh upload,
     * which is what lets a tab survive a reload or a session switch: the tab list is
     * restored from local storage, the parsed cache is not, and this pulls it back.
     */
    ensurePreview: async (kind, refId, opts) => {
      if (!refId) return;
      const cached = kind === "file" ? get().filePreviews : get().outputPreviews;
      if (cached[refId] && !opts?.force) return;

      const running = inflight.get(refId);
      if (running && !opts?.force) return running;

      const task = (async () => {
        try {
          const buffer =
            kind === "file"
              ? await api.downloadUploadedFile(refId)
              : await api.download(refId);
          const preview = parseWorkbook(buffer, opts?.name ?? `${refId}.xlsx`);
          set((s) => {
            const { [refId]: _drop, ...restErrors } = s.previewErrors;
            void _drop;
            return {
              ...(kind === "file"
                ? { filePreviews: { ...s.filePreviews, [refId]: preview } }
                : { outputPreviews: { ...s.outputPreviews, [refId]: preview } }),
              previewErrors: restErrors,
            };
          });
        } catch (err) {
          const message = err instanceof Error ? err.message : "无法解析该文件";
          set((s) => ({
            previewErrors: {
              ...s.previewErrors,
              [refId]: kind === "file" ? message : "结果文件解析失败，请下载查看",
            },
          }));
        }
      })();

      inflight.set(refId, task);
      try {
        await task;
      } finally {
        inflight.delete(refId);
      }
    },

    removeFile: (fileId: string) => {
      set((s) => {
        const { [fileId]: _preview, ...rest } = s.filePreviews;
        void _preview;
        const { [fileId]: _err, ...restErrors } = s.previewErrors;
        void _err;
        return {
          files: s.files.filter((f) => f.id !== fileId),
          filePreviews: rest,
          previewErrors: restErrors,
          ...(s.activePreview?.kind === "file" && s.activePreview.fileId === fileId
            ? { activePreview: null }
            : {}),
        };
      });
    },
  };
}