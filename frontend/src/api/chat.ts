import {
  chatRequestSchema,
  chatResponseSchema,
  type ChatRequest,
  type ChatResponse,
  type GraphDto,
} from "./contracts";
import { httpClient, postSse, type RequestOptions } from "./http";

export type StreamSegment =
  | { type: "text"; content: string }
  | {
      type: "tool";
      call: { tool: string; status: "ok" | "error"; summary: string; output_id?: string | null };
      output_name?: string | null;
    };

export function chat(payload: ChatRequest, options?: RequestOptions): Promise<ChatResponse> {
  // Validate on the wire boundary — keeps hooks free of duplication.
  const body = chatRequestSchema.parse(payload);
  return httpClient.postJson<ChatResponse>("/chat", body, chatResponseSchema, options);
}

export type StreamEvent =
  | { type: "model_call" }
  | { type: "model_response"; stop_reason: string }
  | { type: "text"; delta: string }
  | { type: "tool_start"; name: string; id: string }
  | { type: "tool_end"; id?: string; name: string; summary: string; status: string; output_id?: string | null; output_name?: string | null }
  | { type: "stage_change"; stage: string }
  | { type: "done"; reply: string; tool_calls: StreamToolCall[]; output_id?: string | null; output_name?: string | null; sheets: string[]; segments?: StreamSegment[]; stage?: string; graph?: GraphDto }
  | { type: "error"; code: string; message: string };

export type StreamToolCall = {
  tool: string;
  status: "ok" | "error";
  summary: string;
  output_id?: string | null;
  output_name?: string | null;
};

export async function chatStream(
  payload: ChatRequest,
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const body = chatRequestSchema.parse(payload);
  return postSse("/chat/stream", body, signal);
}

export async function readSseStream<T = StreamEvent>(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: T) => void,
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLines = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim());
      if (!dataLines.length) continue;
      const payload = dataLines.join("\n");
      if (!payload || payload === "[DONE]") continue;
      try {
        const parsed = JSON.parse(payload) as T;
        onEvent(parsed);
      } catch {
        // Skip malformed line — model clients should tolerate the occasional bad frame.
      }
    }
  }
}
