import {
  chatRequestSchema,
  chatResponseSchema,
  type ChatRequest,
  type ChatResponse,
} from "./contracts";
import { ApiError, getApiBase, httpClient, newRequestId, type RequestOptions } from "./http";

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
  | { type: "tool_end"; name: string; summary: string; status: string; output_id?: string | null }
  | { type: "done"; reply: string; tool_calls: StreamToolCall[]; output_id: string | null; sheets: string[] }
  | { type: "error"; code: string; message: string };

export type StreamToolCall = {
  tool: string;
  status: "ok" | "error";
  summary: string;
  output_id?: string | null;
};

export async function chatStream(
  payload: ChatRequest,
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const body = chatRequestSchema.parse(payload);
  const requestId = newRequestId();
  const response = await fetch(`${getApiBase()}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-Request-ID": requestId,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    throw new ApiError({
      status: response.status,
      errorCode: "http_error",
      message: `SSE 请求失败 ${response.status}`,
      requestId,
    });
  }
  if (!response.body) {
    throw new ApiError({
      status: 0,
      errorCode: "http_error",
      message: "SSE 响应无 body",
      requestId,
    });
  }
  return response.body.getReader();
}

export async function readSseStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
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
        const parsed = JSON.parse(payload) as StreamEvent;
        onEvent(parsed);
      } catch {
        // Skip malformed line — model clients should tolerate the occasional bad frame.
      }
    }
  }
}
