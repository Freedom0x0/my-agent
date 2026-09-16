import { fileUploadResponseSchema, type FileUploadResponse } from "./contracts";
import { ApiError, getApiBase, httpClient, newRequestId, type RequestOptions } from "./http";

export function uploadFile(file: File, options?: RequestOptions): Promise<FileUploadResponse> {
  return httpClient.postForm<FileUploadResponse>(
    "/files",
    (() => {
      const fd = new FormData();
      fd.append("file", file);
      return fd;
    })(),
    fileUploadResponseSchema,
    options,
  );
}

export function downloadUrl(outputId: string): string {
  return `${getApiBase()}/outputs/${outputId}`;
}

export async function download(outputId: string, options?: RequestOptions): Promise<ArrayBuffer> {
  const requestId = newRequestId();
  const controller = new AbortController();
  const timeoutMs = options?.timeoutMs ?? 60_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${getApiBase()}/outputs/${outputId}`, {
      method: "GET",
      signal: options?.signal ?? controller.signal,
      headers: { "X-Request-ID": requestId, Accept: "*/*" },
    });
    if (!response.ok) {
      throw new ApiError({
        status: response.status,
        errorCode: "http_error",
        message: `下载失败 ${response.status}`,
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
        message: "下载超时",
        requestId,
      });
    }
    throw new ApiError({
      status: 0,
      errorCode: "network_error",
      message: "下载失败",
      requestId,
    });
  } finally {
    clearTimeout(timer);
  }
}
