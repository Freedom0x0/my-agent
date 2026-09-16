import { ApiError, api, chatStream, readSseStream } from "../../../api/httpClient";
import type { StreamEvent, StreamToolCall } from "../../../api/httpClient";
import { makeUserFacingError } from "../../../api/mappers";
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
      const streamingId = newMessageId();
      const controller = new AbortController();

      set({
        status: "processing",
        messages: [...s.messages, userMsg],
        streamingContent: "",
        streamingMessageId: streamingId,
        streamController: controller,
        lastChatToolCalls: [],
        error: null,
      });

      const accumulatedReply: { value: string } = { value: "" };
      const toolCallsBox: { value: StreamToolCall[] } = { value: [] };
      const doneBox: { value: { reply: string; tool_calls: StreamToolCall[]; output_id: string | null; sheets: string[] } | null } = { value: null };
      const errorBox: { value: { code: string; message: string } | null } = { value: null };

      const finish = (status: "completed" | "error", error?: { code: string; message: string }) => {
        if (status === "completed" && doneBox.value) {
          const doneEvent = doneBox.value;
          const assistantId = newMessageId();
          const assistantMsg: ChatMessage = {
            id: assistantId,
            role: "assistant",
            content: accumulatedReply.value || doneEvent.reply,
            toolCalls: toolCallsBox.value.map((t) => ({
              tool: t.tool,
              status: t.status,
              summary: t.summary,
              outputId: t.output_id ?? null,
            })),
            outputId: doneEvent.output_id ?? null,
            sheets: doneEvent.sheets ?? [],
            timestamp: Date.now(),
          };
          const outputId = doneEvent.output_id ?? null;
          const sheets = doneEvent.sheets ?? [];
          set((cur) => ({
            status: "completed",
            messages: [...cur.messages, assistantMsg],
            streamingContent: "",
            streamingMessageId: null,
            streamController: null,
            outputIds: outputId && !cur.outputIds.includes(outputId)
              ? [...cur.outputIds, outputId]
              : cur.outputIds,
            lastChatSheets: sheets,
            lastChatOutputId: outputId,
            lastChatToolCalls: toolCallsBox.value.map((t) => ({
              tool: t.tool,
              status: t.status,
              summary: t.summary,
              outputId: t.output_id ?? null,
            })),
          }));

          if (outputId) {
            get().addTab(sessionId, {
              kind: "output",
              refId: outputId,
              fileName: `${outputId}.xlsx`,
            });
            (async () => {
              try {
                const buffer = await api.download(outputId);
                const preview = parseWorkbook(buffer, `${outputId}.xlsx`);
                set((cur) => ({
                  outputPreviews: { ...cur.outputPreviews, [outputId]: preview },
                }));
              } catch {
                set({ previewError: "结果文件解析失败，请点击下方按钮下载查看" });
              }
            })();
          }

          void get().loadSessions();
        } else {
          const code = error?.code ?? "network_error";
          const message = error?.message ?? "请求失败";
          set({
            status: "error",
            error: makeUserFacingError(code, message),
            streamingContent: "",
            streamingMessageId: null,
            streamController: null,
          });
        }
      };

      try {
        const reader = await chatStream(
          { message: trimmed, file_ids: fileIds, session_id: sessionId },
          controller.signal,
        );

        await readSseStream(reader, (evt: StreamEvent) => {
          switch (evt.type) {
            case "text":
              accumulatedReply.value += evt.delta;
              get().appendStream(evt.delta);
              break;
            case "tool_start":
              toolCallsBox.value.push({ tool: evt.name, status: "ok", summary: "(运行中)" });
              break;
            case "tool_end": {
              const list = toolCallsBox.value;
              const last = list[list.length - 1];
              if (last && last.tool === evt.name) {
                last.status = evt.status as "ok" | "error";
                last.summary = evt.summary;
                last.output_id = evt.output_id ?? null;
              } else {
                list.push({
                  tool: evt.name,
                  status: evt.status as "ok" | "error",
                  summary: evt.summary,
                  output_id: evt.output_id ?? null,
                });
              }
              break;
            }
            case "done":
              doneBox.value = {
                reply: evt.reply,
                tool_calls: evt.tool_calls,
                output_id: evt.output_id,
                sheets: evt.sheets,
              };
              break;
            case "error":
              errorBox.value = { code: evt.code, message: evt.message };
              break;
            default:
              break;
          }
        });

        if (errorBox.value && !doneBox.value) {
          finish("error", errorBox.value);
        } else {
          finish("completed");
        }
      } catch (err) {
        if ((err as { name?: string }).name === "AbortError") {
          set({
            status: "idle",
            streamingContent: "",
            streamingMessageId: null,
            streamController: null,
          });
          return;
        }
        if (errorBox.value) {
          finish("error", errorBox.value);
          return;
        }
        const apiErr =
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, errorCode: "network_error", message: "请求失败" });
        finish("error", { code: apiErr.errorCode, message: apiErr.message });
      }
    },

    clearError: () => set({ error: null }),
  };
}
