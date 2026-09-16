import { z } from "zod";

import { errorResponseSchema, type ErrorResponse } from "./contracts";

const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly details: unknown;
  readonly requestId: string;

  constructor(opts: {
    status: number;
    errorCode: string;
    message: string;
    details?: unknown;
    requestId?: string;
  }) {
    super(opts.message);
    this.status = opts.status;
    this.errorCode = opts.errorCode;
    this.details = opts.details;
    this.requestId = opts.requestId ?? "";
  }
}

export type RequestOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
  isBinary?: boolean;
};

export function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

async function parseBody<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  const text = await response.text();
  if (!text) {
    throw new ApiError({
      status: response.status,
      errorCode: "http_error",
      message: "服务器返回空响应",
    });
  }
  try {
    const json = JSON.parse(text);
    const parsed = schema.safeParse(json);
    if (!parsed.success) {
      throw new ApiError({
        status: response.status,
        errorCode: "http_error",
        message: "服务器响应格式错误",
      });
    }
    return parsed.data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError({
      status: response.status,
      errorCode: "http_error",
      message: "无法解析服务器响应",
    });
  }
}

export async function request<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>,
  options: RequestOptions = {},
): Promise<T> {
  const requestId = newRequestId();
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? (init.method === "GET" ? 30_000 : 180_000);
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const signal = options.signal ?? controller.signal;

  const headers = new Headers(init.headers);
  headers.set("X-Request-ID", requestId);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal,
    });
  } catch (err) {
    if ((err as { name?: string }).name === "AbortError") {
      throw new ApiError({
        status: 0,
        errorCode: "request_timeout",
        message: "请求超时，请稍后重试",
        requestId,
      });
    }
    throw new ApiError({
      status: 0,
      errorCode: "network_error",
      message: "网络连接异常，请稍后重试",
      requestId,
    });
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    let parsedError: ErrorResponse | null = null;
    try {
      const json = await response.json();
      parsedError = errorResponseSchema.parse(json);
    } catch {
      // ignore
    }
    throw new ApiError({
      status: response.status,
      errorCode: parsedError?.error_code ?? "http_error",
      message: parsedError?.message ?? `请求失败 ${response.status}`,
      details: parsedError?.details,
      requestId,
    });
  }

  return parseBody(response, schema);
}

export const httpClient = {
  getJson<T>(path: string, schema: z.ZodType<T>, options?: RequestOptions) {
    return request<T>(path, { method: "GET" }, schema, options);
  },
  postJson<T>(path: string, body: unknown, schema: z.ZodType<T>, options?: RequestOptions) {
    return request<T>(path, { method: "POST", body: JSON.stringify(body) }, schema, options);
  },
  postForm<T>(path: string, form: FormData, schema: z.ZodType<T>, options?: RequestOptions) {
    return request<T>(path, { method: "POST", body: form }, schema, options);
  },
};

export function getApiBase(): string {
  return API_BASE;
}
