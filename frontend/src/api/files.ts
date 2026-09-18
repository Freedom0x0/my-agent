import { fileUploadResponseSchema, type FileUploadResponse } from "./contracts";
import { ApiError, getApiBase, httpClient, newRequestId, type RequestOptions } from "./http";

export function uploadFile(
  file: File,
  sessionId?: string | null,
  options?: RequestOptions,
): Promise<FileUploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  // Ties the upload to its conversation so the file comes back with the session.
  if (sessionId) fd.append("session_id", sessionId);
  return httpClient.postForm<FileUploadResponse>("/files", fd, fileUploadResponseSchema, options);
}

export function downloadUrl(outputId: string): string {
  return `${getApiBase()}/outputs/${outputId}`;
}

async function fetchBytes(path: string, what: string, options?: RequestOptions): Promise<ArrayBuffer> {
  const requestId = newRequestId();
  const controller = new AbortController();
  const timeoutMs = options?.timeoutMs ?? 60_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      method: "GET",
      signal: options?.signal ?? controller.signal,
      headers: { "X-Request-ID": requestId, Accept: "*/*" },
    });
    if (!response.ok) {
      throw new ApiError({
        status: response.status,
        errorCode: "http_error",
        message: `${what}失败 ${response.status}`,
        requestId,
      });
    }
    return await response.arrayBuffer();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if ((err as { name?: string }).name === "AbortError") {
      throw new ApiError({
        status: 0,
        errorCode: "request_timeout",
        message: `${what}超时`,
        requestId,
      });
    }
    throw new ApiError({ status: 0, errorCode: "network_error", message: `${what}失败`, requestId });
  } finally {
    clearTimeout(timer);
  }
}

/** Bytes of a generated output, for previewing it client-side. */
export function download(outputId: string, options?: RequestOptions): Promise<ArrayBuffer> {
  return fetchBytes(`/outputs/${outputId}`, "下载", options);
}

/** Bytes of an originally uploaded file, so its preview survives a reload. */
export function downloadUploadedFile(fileId: string, options?: RequestOptions): Promise<ArrayBuffer> {
  return fetchBytes(`/files/${fileId}/content`, "下载", options);
}