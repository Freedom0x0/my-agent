import { ApiError, api } from "../../../api/httpClient";
import { makeUserFacingError, mapChatResponseToAssistantMessage } from "../../../api/mappers";
import { parseWorkbook } from "../../useSpreadsheet";
import type { ChatMessage } from "../../../domain/workflow";
import { newMessageId } from "../types";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function chatActions(set: Set, get: Get): Pick<Actions, "sendMessage" | "clearError"> {
  return {
    sendMessage: async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const s = get();
      if (s.status === "processing" || s.status === "uploading") return;
      if (s.files.length === 0) return;

      const sessionId = s.currentSessionId ?? get().createSession();
      const userMsg: ChatMessage = {
        id: newMessageId(),
        role: "user",
        content: trimmed,
        timestamp: Date.now(),
      };
      const fileIds = s.files.map((f) => f.id);
      set({
        status: "processing",
        messages: [...s.messages, userMsg],
        streamingContent: "",
        error: null,
      });

      try {
        const resp = await api.chat({
          message: trimmed,
          file_ids: fileIds,
          session_id: sessionId,
        });
        if (resp.error_code) {
          set({
            status: "error",
            error: makeUserFacingError(resp.error_code, resp.reply),
            messages: s.messages.filter((m) => m.id !== userMsg.id),
          });
          return;
        }
        const assistantId = newMessageId();
        const assistantMsg = mapChatResponseToAssistantMessage(resp, assistantId);
        const outputId = resp.output_id ?? null;
        const sheets = resp.sheets ?? [];
        set((cur) => ({
          status: "completed",
          messages: [...cur.messages, assistantMsg],
          streamingContent: "",
          outputIds: outputId && !cur.outputIds.includes(outputId)
            ? [...cur.outputIds, outputId]
            : cur.outputIds,
          lastChatSheets: sheets,
          lastChatOutputId: outputId,
        }));

        // Add a tab for the new output (if any) and activate it.
        if (outputId) {
          get().addTab(sessionId, {
            kind: "output",
            refId: outputId,
            fileName: `${outputId}.xlsx`,
          });
          try {
            const buffer = await api.download(outputId);
            const preview = parseWorkbook(buffer, `${outputId}.xlsx`);
            set((cur) => ({
              outputPreviews: { ...cur.outputPreviews, [outputId]: preview },
            }));
          } catch {
            set({ previewError: "结果文件解析失败，请点击下方按钮下载查看" });
          }
        }

        void get().loadSessions();
      } catch (err) {
        const apiErr =
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, errorCode: "network_error", message: "请求失败" });
        set({
          status: "error",
          error: makeUserFacingError(apiErr.errorCode, apiErr.message),
          messages: s.messages.filter((m) => m.id !== userMsg.id),
          streamingContent: "",
        });
      }
    },

    clearError: () => set({ error: null }),
  };
}
