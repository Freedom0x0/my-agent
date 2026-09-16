import {
  chatRequestSchema,
  chatResponseSchema,
  type ChatRequest,
  type ChatResponse,
} from "./contracts";
import { httpClient, type RequestOptions } from "./http";

export function chat(payload: ChatRequest, options?: RequestOptions): Promise<ChatResponse> {
  // Validate on the wire boundary — keeps hooks free of duplication.
  const body = chatRequestSchema.parse(payload);
  return httpClient.postJson<ChatResponse>("/chat", body, chatResponseSchema, options);
}
