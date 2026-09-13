import { auditResponseSchema, errorResponseSchema, executionResponseSchema, fileUploadResponseSchema, planResponseSchema, } from "./contracts";
const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";
export class ApiError extends Error {
    status;
    errorCode;
    details;
    requestId;
    constructor(opts) {
        super(opts.message);
        this.status = opts.status;
        this.errorCode = opts.errorCode;
        this.details = opts.details;
        this.requestId = opts.requestId ?? "";
    }
}
function newRequestId() {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
        return crypto.randomUUID();
    }
    return Math.random().toString(36).slice(2);
}
async function parseBody(response, schema) {
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
    }
    catch (err) {
        if (err instanceof ApiError)
            throw err;
        throw new ApiError({
            status: response.status,
            errorCode: "http_error",
            message: "无法解析服务器响应",
        });
    }
}
async function request(path, init, schema, options = {}) {
    const requestId = newRequestId();
    const controller = new AbortController();
    const timeoutMs = options.timeoutMs ?? (init.method === "GET" ? 30_000 : 120_000);
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
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, {
            ...init,
            headers,
            signal,
        });
    }
    catch (err) {
        if (err.name === "AbortError") {
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
    }
    finally {
        clearTimeout(timer);
    }
    if (!response.ok) {
        let parsedError = null;
        try {
            const json = await response.json();
            parsedError = errorResponseSchema.parse(json);
        }
        catch {
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
    getJson(path, schema, options) {
        return request(path, { method: "GET" }, schema, options);
    },
    postJson(path, body, schema, options) {
        return request(path, { method: "POST", body: JSON.stringify(body) }, schema, options);
    },
    postForm(path, form, schema, options) {
        return request(path, { method: "POST", body: form }, schema, options);
    },
};
export const api = {
    uploadFile: (file, options) => httpClient.postForm("/files", (() => {
        const fd = new FormData();
        fd.append("file", file);
        return fd;
    })(), fileUploadResponseSchema, options),
    createPlan: (fileIds, requestText, options) => httpClient.postJson("/plans", { file_ids: fileIds, request: requestText }, planResponseSchema, options),
    executePlan: (fileIds, plan, confirmationToken, options) => httpClient.postJson("/executions", { file_ids: fileIds, plan, confirmation_token: confirmationToken }, executionResponseSchema, options),
    getAudit: (outputId, options) => httpClient.getJson(`/outputs/${outputId}/audit`, auditResponseSchema, options),
    downloadUrl: (outputId) => `${API_BASE}/outputs/${outputId}`,
};
