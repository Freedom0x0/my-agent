import { ApiError, chatStream, readSseStream } from "../../../api/httpClient";
import type { StreamEvent } from "../../../api/httpClient";
import { makeUserFacingError, mapGraph, mapStage } from "../../../api/mappers";
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
      const assistantId = newMessageId();
      const controller = new AbortController();

      // The assistant message is committed up front with `streaming: true`. Every
      // event below appends to its `segments`, and the turn ends by just clearing
      // that flag — so what the user watches stream in IS the final message.
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        segments: [],
        streaming: true,
        timestamp: Date.now(),
      };

      set({
        status: "processing",
        messages: [...s.messages, userMsg, assistantMsg],
        streamingMessageId: assistantId,
        streamController: controller,
        error: null,
      });

      const errorBox: { value: { code: string; message: string } | null } = { value: null };
      const doneBox: { value: Extract<StreamEvent, { type: "done" }> | null } = { value: null };
      const outputBox: { value: { id: string | null; name: string | null } } = { value: { id: null, name: null } };
      // Tracks whether the current text run still accepts deltas. A new model round
      // (`model_call`) closes it so each round lands as its own segment, matching
      // the server-built transcript that gets persisted.
      let textRunOpen = false;
      // Whether any text actually arrived as deltas — if not, `done.reply` is the
      // only copy of the answer we have.
      let sawText = false;

      const rememberOutput = (id: string | null | undefined, name: string | null | undefined) => {
        if (!name) return;
        if (outputBox.value.name === name && outputBox.value.id === (id ?? null)) return;
        outputBox.value = { id: id ?? null, name };
        // No id means no bytes to preview — a tab here would spin forever. The
        // chat bubble's chip can still open it once the id is known.
        if (!id) return;
        get().addTab(sessionId, {
          kind: "output",
          fileName: name,
          outputName: name,
          refId: id,
        });
      };

      try {
        const reader = await chatStream(
          { message: trimmed, file_ids: fileIds, session_id: sessionId },
          controller.signal,
        );

        await readSseStream(reader, (evt: StreamEvent) => {
          switch (evt.type) {
            case "model_call":
              textRunOpen = false;
              break;
            case "text":
              get().appendTextDelta(evt.delta, { separate: !textRunOpen });
              textRunOpen = true;
              sawText = true;
              break;
            case "tool_start":
              get().pushToolStart(evt.id, evt.name);
              break;
            case "tool_end":
              get().resolveTool({
                id: evt.id,
                name: evt.name,
                status: evt.status === "error" ? "error" : "ok",
                summary: evt.summary,
                outputId: evt.output_id,
                outputName: evt.output_name,
              });
              rememberOutput(evt.output_id, evt.output_name);
              break;
            case "done":
              doneBox.value = evt;
              break;
            case "stage_change": {
              const stage = mapStage(evt.stage);
              if (stage) get().setStage(stage);
              break;
            }
            case "error":
              errorBox.value = { code: evt.code, message: evt.message };
              break;
            default:
              break;
          }
        });

        // An abort can surface as a clean end-of-stream rather than a thrown
        // AbortError — either way it's a stop, not a failure.
        if (controller.signal.aborted) {
          get().endStreamMessage();
          set({ status: "idle" });
          return;
        }

        if (errorBox.value && !doneBox.value) {
          const friendly = makeUserFacingError(errorBox.value.code, errorBox.value.message);
          get().appendTextDelta(friendly.message, { separate: true });
          get().endStreamMessage();
          set({ status: "error", error: friendly });
          return;
        }

        // `done` carries the authoritative graph + stage for this turn.
        const done = doneBox.value;
        if (done?.graph) {
          get().applyGraph(mapGraph(done.graph), mapStage(done.stage));
        } else if (done?.stage) {
          const stage = mapStage(done.stage);
          if (stage) get().setStage(stage);
        }

        if (!doneBox.value) {
          // The stream closed without a terminal event — don't call that a success.
          const friendly = makeUserFacingError("network_error", "连接中断");
          get().appendTextDelta(friendly.message, { separate: true });
          get().endStreamMessage();
          set({ status: "error", error: friendly });
          return;
        }

        // Insurance: if the model produced text that never arrived as deltas, keep it.
        if (done?.reply && !sawText) {
          get().appendTextDelta(done.reply, { separate: true });
        }
        // `done` also carries the last output — normally already remembered from
        // tool_end, but keep the fallback so the contract holds either way.
        rememberOutput(done?.output_id, done?.output_name);

        const sheets = done?.sheets ?? [];
        const finalOutputName = outputBox.value.name;
        const finalOutputId = outputBox.value.id;
        get().endStreamMessage({
          outputId: finalOutputId,
          outputName: finalOutputName,
          sheets,
        });
        if (finalOutputId) {
          set((cur) => ({
            outputIds: cur.outputIds.includes(finalOutputId)
              ? cur.outputIds
              : [...cur.outputIds, finalOutputId],
          }));
        }
        set({
          status: "completed",
          lastChatSheets: sheets,
          lastChatOutputId: finalOutputId,
          lastChatOutputName: finalOutputName,
        });

        void get().loadSessions();
      } catch (err) {
        if ((err as { name?: string }).name === "AbortError") {
          get().endStreamMessage();
          set({ status: "idle" });
          return;
        }
        if (errorBox.value) {
          const friendly = makeUserFacingError(errorBox.value.code, errorBox.value.message);
          get().appendTextDelta(friendly.message, { separate: true });
          get().endStreamMessage();
          set({ status: "error", error: friendly });
          return;
        }
        const apiErr =
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, errorCode: "network_error", message: "请求失败" });
        const friendly = makeUserFacingError(apiErr.errorCode, apiErr.message);
        get().appendTextDelta(friendly.message, { separate: true });
        get().endStreamMessage();
        set({ status: "error", error: friendly });
      }
    },

    clearError: () => set({ error: null }),
  };
}