import type { Actions, WorkflowState } from "../types";
import type { ChatMessage, Segment, ToolStatus } from "../../../domain/models";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

// Stable refs: a fresh [] every call would break identity for untouched messages.
const EMPTY_SEGMENTS: Segment[] = [];

/**
 * Patch the tail message (the one being streamed) and leave every other message
 * object untouched, so their bubbles keep their identity and skip re-render.
 */
function patchTail(
  messages: ChatMessage[],
  patch: (m: ChatMessage) => ChatMessage,
): ChatMessage[] {
  if (!messages.length) return messages;
  return [...messages.slice(0, -1), patch(messages[messages.length - 1])];
}

function lastToolIndex(segments: Segment[], match: (c: Segment & { type: "tool" }) => boolean): number {
  for (let i = segments.length - 1; i >= 0; i -= 1) {
    const seg = segments[i];
    if (seg.type === "tool" && match(seg)) return i;
  }
  return -1;
}

function textOf(segments: Segment[]): string {
  return segments
    .filter((s): s is Segment & { type: "text" } => s.type === "text")
    .map((s) => s.content)
    .join("");
}

export function streamActions(
  set: Set,
  get: Get,
): Pick<Actions, "appendTextDelta" | "pushToolStart" | "resolveTool" | "endStreamMessage" | "abortStream"> {
  return {
    /**
     * Append a text delta to the in-flight message. Merges into the trailing text
     * segment unless `separate` is set, which opens a new one — and so is how the
     * timeline keeps one segment per model round, matching the server's transcript.
     */
    appendTextDelta: (delta, opts) => {
      if (!delta) return;
      // ponytail: one store write per token, each re-parsing the whole markdown of
      // this bubble. Fine at chat length; batch deltas into a rAF if long answers lag.
      set((s) => ({
        // The model spoke while the user was looking at the canvas — flag it, or
        // the answer is missed until they think to switch back.
        chatUnread: s.workspaceView === "chat" ? s.chatUnread : true,
        messages: patchTail(s.messages, (m) => {
          const segs = m.segments ?? EMPTY_SEGMENTS;
          const tail = segs[segs.length - 1];
          const next: Segment[] =
            !opts?.separate && tail?.type === "text"
              ? [...segs.slice(0, -1), { type: "text", content: tail.content + delta }]
              : [...segs, { type: "text", content: delta }];
          return { ...m, segments: next };
        }),
      }));
    },

    pushToolStart: (id, name) => {
      set((s) => ({
        messages: patchTail(s.messages, (m) => ({
          ...m,
          segments: [
            ...(m.segments ?? EMPTY_SEGMENTS),
            { type: "tool", call: { tool: name, id, status: "running" as ToolStatus, summary: "" } },
          ],
        })),
      }));
    },

    resolveTool: ({ id, name, status, summary, outputId, outputName }) => {
      set((s) => ({
        messages: patchTail(s.messages, (m) => {
          const segs = m.segments ?? EMPTY_SEGMENTS;
          let idx = id
            ? lastToolIndex(segs, (seg) => seg.call.id === id)
            : -1;
          if (idx < 0) {
            // Older backends sent no id on tool_end — fall back to the newest running
            // call with the same tool name.
            idx = lastToolIndex(
              segs,
              (seg) => seg.call.tool === name && seg.call.status === "running",
            );
          }
          if (idx < 0) return m;
          const prev = segs[idx] as Segment & { type: "tool" };
          const next = [...segs];
          next[idx] = {
            type: "tool",
            call: { ...prev.call, status, summary, outputId: outputId ?? null, outputName: outputName ?? null },
            outputName: outputName ?? null,
          };
          return { ...m, segments: next };
        }),
      }));
    },

    /**
     * Close the in-flight message: drop the `streaming` flag in place (same id, same
     * segments, so the rendered timeline does not change), backfill `content` for the
     * copy button, and drop the bubble entirely if the turn produced nothing.
     */
    endStreamMessage: (meta) => {
      set((s) => {
        const msgs = s.messages;
        const last = msgs[msgs.length - 1];
        // Idempotent: an abort already closed the message, so the second call must
        // not walk one step further and delete the user's turn.
        if (!last || last.role !== "assistant") {
          return { streamingMessageId: null, streamController: null };
        }
        const keep = !!last.segments?.length;
        return {
          messages: keep
            ? patchTail(msgs, (m) => ({
                ...m,
                streaming: false,
                content: textOf(m.segments ?? EMPTY_SEGMENTS),
                ...(meta
                  ? {
                      outputId: meta.outputId ?? null,
                      outputName: meta.outputName ?? null,
                      sheets: meta.sheets ?? [],
                    }
                  : {}),
              }))
            : msgs.slice(0, -1),
          streamingMessageId: null,
          streamController: null,
        };
      });
    },

    abortStream: () => {
      get().streamController?.abort();
      get().endStreamMessage();
    },
  };
}