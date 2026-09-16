import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { api } from "../api/httpClient";
import { useAppStore } from "../hooks/useAppStore";

// Hoisted so tests below can reference them.
const hoisted = vi.hoisted(() => ({
  sseMock: {
    chatStream: vi.fn(),
    readSseStream: vi.fn(),
  },
}));

vi.mock("../api/httpClient", async () => {
  const actual = await vi.importActual<typeof import("../api/httpClient")>(
    "../api/httpClient",
  );
  return {
    ...actual,
    api: {
      uploadFile: vi.fn(),
      chat: vi.fn(),
      listSessions: vi.fn().mockResolvedValue([]),
      getSession: vi.fn(),
      downloadUrl: vi.fn((id: string) => `/api/outputs/${id}`),
      download: vi.fn().mockRejectedValue(new Error("not mocked")),
    },
    chatStream: hoisted.sseMock.chatStream,
    readSseStream: hoisted.sseMock.readSseStream,
  };
});

const mockedApi = api as unknown as {
  uploadFile: ReturnType<typeof vi.fn>;
  chat: ReturnType<typeof vi.fn>;
  listSessions: ReturnType<typeof vi.fn>;
  getSession: ReturnType<typeof vi.fn>;
  downloadUrl: ReturnType<typeof vi.fn>;
  download: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.clear();
  }
  mockedApi.listSessions.mockResolvedValue([]);
  hoisted.sseMock.chatStream.mockReset();
  hoisted.sseMock.readSseStream.mockReset();
  // Default: chatStream returns a dummy reader; readSseStream invokes onEvent
  // with nothing. Tests that need SSE behavior override these directly.
  hoisted.sseMock.chatStream.mockResolvedValue({} as ReadableStreamDefaultReader<Uint8Array>);
  hoisted.sseMock.readSseStream.mockResolvedValue(undefined);
  useAppStore.setState({
    sessions: [],
    sessionsLoading: false,
    currentSessionId: null,
    status: "idle",
    files: [],
    messages: [],
    outputIds: [],
    activePreview: null,
    filePreviews: {},
    outputPreviews: {},
    previewLoading: false,
    previewError: null,
    tabsBySession: {},
    activeTabBySession: {},
    streamingContent: "",
    streamingMessageId: null,
    streamController: null,
    lastChatToolCalls: [],
    lastChatSheets: [],
    lastChatOutputId: null,
    error: null,
  });
});

const sampleUploadResponse = () => ({
  file_id: "f-1",
  filename: "sample.xlsx",
  size_bytes: 1024,
  inspection: {
    filename: "sample.xlsx",
    file_type: "xlsx",
    sheets: [
      {
        name: "明细",
        row_count: 3,
        column_count: 3,
        columns: [
          { name: "部门", inferred_type: "text", null_count: 0, unique_count: 2, sample_values: [] },
          { name: "金额", inferred_type: "number", null_count: 0, unique_count: 3, sample_values: [] },
        ],
        preview: [],
        issues: [],
        formula_count: 0,
      },
    ],
  },
});

describe("App three-pane workflow", () => {
  it("renders the three-pane shell on mount", () => {
    const { container } = render(<App />);
    expect(container.querySelector(".workspace-sider")).toBeInTheDocument();
    expect(container.querySelector(".workspace-chat")).toBeInTheDocument();
    expect(container.querySelector(".workspace-preview")).toBeInTheDocument();
  });

  it("uploads via the store and shows the file name", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());

    render(<App />);

    const file = new File(["hello"], "sample.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await useAppStore.getState().uploadFile(file);

    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());
    // File name appears at least once (in previewer tabs and/or Attachments).
    expect(screen.getAllByText("sample.xlsx").length).toBeGreaterThan(0);
  });

  it("sends a chat via the store and shows assistant message", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());

    // Provide an SSE stream that yields a single "done" event with a reply.
    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({
          type: "done",
          reply: "处理完成，文件 = 清洗后数据",
          tool_calls: [
            { tool: "tablex_normalize", status: "ok", summary: "统一金额格式" },
            { tool: "tablex_export", status: "ok", summary: "导出结果", output_id: "out-1" },
          ],
          output_id: "out-1",
          sheets: ["清洗后数据"],
        });
      },
    );

    render(<App />);

    await useAppStore
      .getState()
      .uploadFile(
        new File(["x"], "sample.xlsx", {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }),
      );
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());

    await useAppStore.getState().sendMessage("检查并清洗");

    await waitFor(() => expect(hoisted.sseMock.chatStream).toHaveBeenCalled());

    // The assistant reply text should be somewhere in the chat section
    await waitFor(() => {
      const chatSection = document.querySelector(".workspace-chat");
      expect(chatSection?.textContent).toContain("清洗后数据");
    });

    // Sheet link rendered through the assistant text
    const link = await screen.findByTestId("sheet-link");
    expect(link.textContent).toContain("清洗后数据");
  });

  it("creates a new session via store action", () => {
    render(<App />);
    const before = useAppStore.getState().currentSessionId;
    useAppStore.getState().createSession();
    const after = useAppStore.getState().currentSessionId;
    expect(after).toBeTruthy();
    expect(after).not.toBe(before);
  });

  it("adds a tab per uploaded file and lists it in the right pane", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    render(<App />);

    const file = new File(["x"], "sample.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await useAppStore.getState().uploadFile(file);
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());

    const sid = useAppStore.getState().currentSessionId!;
    const tabs = useAppStore.getState().tabsBySession[sid] ?? [];
    expect(tabs.length).toBeGreaterThan(0);
    expect(tabs[0].kind).toBe("file");
    expect(tabs[0].fileName).toBe("sample.xlsx");
    await waitFor(() => {
      expect(screen.getAllByTestId("tab-item").length).toBeGreaterThan(0);
    });
  });

  it("removes a tab and clears active preview when last tab closes", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    render(<App />);
    await useAppStore.getState().uploadFile(
      new File(["x"], "sample.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());

    const sid = useAppStore.getState().currentSessionId!;
    const tabId = useAppStore.getState().tabsBySession[sid][0].id;
    useAppStore.getState().removeTab(sid, tabId);
    expect(useAppStore.getState().tabsBySession[sid].length).toBe(0);
    expect(useAppStore.getState().activePreview).toBeNull();
  });

  it("exposes abortStream on the store", () => {
    expect(typeof useAppStore.getState().abortStream).toBe("function");
  });
});

describe("SSE streaming flow", () => {
  async function setupWithFile(): Promise<void> {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    await useAppStore.getState().uploadFile(
      new File(["x"], "sample.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());
  }

  it("accumulates text deltas into streamingContent", async () => {
    await setupWithFile();
    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "text", delta: "你好" });
        onEvent({ type: "text", delta: "，" });
        onEvent({ type: "text", delta: "世界" });
        onEvent({
          type: "done",
          reply: "你好，世界",
          tool_calls: [],
          output_id: null,
          sheets: [],
        });
      },
    );

    await useAppStore.getState().sendMessage("hi");

    await waitFor(() =>
      expect(useAppStore.getState().streamingContent).toBe(""),
    );
    expect(useAppStore.getState().status).toBe("completed");
    const last = useAppStore.getState().messages.at(-1);
    expect(last?.role).toBe("assistant");
    expect(last?.content).toBe("你好，世界");
  });

  it("records tool_start and tool_end events into lastChatToolCalls", async () => {
    await setupWithFile();
    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "tool_start", name: "tablex_normalize", id: "tu-1" });
        onEvent({
          type: "tool_end",
          name: "tablex_normalize",
          summary: "统一金额格式",
          status: "ok",
          output_id: null,
        });
        onEvent({ type: "text", delta: "done" });
        onEvent({
          type: "done",
          reply: "done",
          tool_calls: [],
          output_id: null,
          sheets: [],
        });
      },
    );

    await useAppStore.getState().sendMessage("检查");

    await waitFor(() =>
      expect(useAppStore.getState().status).toBe("completed"),
    );
    const calls = useAppStore.getState().lastChatToolCalls;
    expect(calls.some((c) => c.tool === "tablex_normalize" && c.summary === "统一金额格式")).toBe(true);
  });

  it("abortStream triggers AbortController and clears streaming state", async () => {
    await setupWithFile();
    let capturedSignal: AbortSignal | undefined;
    hoisted.sseMock.chatStream.mockImplementationOnce(
      async (_payload, signal) => {
        capturedSignal = signal;
        return new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            const err = new Error("aborted");
            err.name = "AbortError";
            reject(err);
          });
        }) as unknown as ReadableStreamDefaultReader<Uint8Array>;
      },
    );
    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "text", delta: "partial " });
        await new Promise<void>((resolve) => {
          if (capturedSignal?.aborted) return resolve();
          capturedSignal?.addEventListener("abort", () => resolve());
        });
      },
    );

    const sendPromise = useAppStore.getState().sendMessage("hi");
    await waitFor(() =>
      expect(useAppStore.getState().streamController).not.toBeNull(),
    );

    useAppStore.getState().abortStream();
    await sendPromise;

    expect(capturedSignal?.aborted).toBe(true);
    expect(useAppStore.getState().status).toBe("idle");
    expect(useAppStore.getState().streamingContent).toBe("");
    expect(useAppStore.getState().streamController).toBeNull();
  });
});