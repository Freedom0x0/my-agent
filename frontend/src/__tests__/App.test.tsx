import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

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

describe("P. Bubble interaction", () => {
  function seedAssistantMessage(): string {
    const id = "assistant-msg-1";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "处理完成，文件 = 清洗后数据",
          toolCalls: [],
          outputId: null,
          sheets: ["清洗后数据"],
          timestamp: Date.now(),
        },
      ],
    });
    return id;
  }

  function seedUserMessage(): string {
    const id = "user-msg-1";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "user",
          content: "原始文本",
          timestamp: Date.now(),
        },
      ],
    });
    return id;
  }

  it("copy button writes assistant content to clipboard and shows 已复制", async () => {
    const id = seedAssistantMessage();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<App />);
    const btn = screen.getByTestId(`copy-btn-${id}`);
    fireEvent.click(btn);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("处理完成，文件 = 清洗后数据"));
    expect(btn.textContent).toContain("已复制");
  });

  it("thumb up / down toggle reaction in store (mutually exclusive)", () => {
    const id = seedAssistantMessage();
    render(<App />);

    fireEvent.click(screen.getByTestId(`thumb-up-${id}`));
    expect(useAppStore.getState().messageReactions[id]).toBe("up");

    fireEvent.click(screen.getByTestId(`thumb-down-${id}`));
    expect(useAppStore.getState().messageReactions[id]).toBe("down");

    fireEvent.click(screen.getByTestId(`thumb-down-${id}`));
    expect(useAppStore.getState().messageReactions[id]).toBeNull();
  });

  it("edit a user message shows textarea; save truncates and triggers sendMessage", async () => {
    const originalSend = useAppStore.getState().sendMessage;
    const sendSpy = vi.fn(async (text: string) => originalSend(text));
    useAppStore.setState({ sendMessage: sendSpy } as Partial<typeof useAppStore.getState>);

    const id = seedUserMessage();
    render(<App />);

    fireEvent.click(screen.getByTestId(`user-bubble-edit-${id}`));
    const ta = screen.getByTestId(`user-bubble-textarea-${id}`) as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "改写后的文本" } });
    fireEvent.click(screen.getByTestId(`user-bubble-save-${id}`));

    await waitFor(() => expect(sendSpy).toHaveBeenCalledWith("改写后的文本"));
    expect(useAppStore.getState().messages[0].content).toBe("改写后的文本");
  });

  afterEach(() => {
    Object.assign(navigator, { clipboard: undefined });
  });
});

describe("Q. Markdown rendering", () => {
  it("renders assistant content via MarkdownContent (paragraphs + code block + sheet link)", () => {
    const id = "md-1";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "已完成清洗，结果是 清洗后数据。\n\n```python\nprint(1)\n```",
          toolCalls: [],
          outputId: "out-1",
          sheets: ["清洗后数据"],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    const md = screen.getByTestId(`assistant-bubble-${id}`);
    expect(md.querySelector(".markdown-content")).toBeInTheDocument();
    expect(md.querySelector("pre")).toBeInTheDocument();
    const link = screen.getByTestId("sheet-link");
    expect(link.textContent).toContain("清洗后数据");
  });
});

describe("R. Tool progress", () => {
  it("renders ToolProgressBar when assistant message has tool calls", () => {
    const id = "r-1";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "完成",
          toolCalls: [
            { tool: "tablex_normalize", status: "ok", summary: "统一金额格式" },
            { tool: "tablex_export", status: "ok", summary: "导出结果", outputId: "out-1" },
          ],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    expect(screen.getByTestId(`tool-progress-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`tool-progress-toggle-${id}`).textContent).toContain("已完成 2 个工具调用");
  });

  it("hides ToolProgressBar when no tool calls", () => {
    const id = "r-2";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "纯文本回复",
          toolCalls: [],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    expect(screen.queryByTestId(`tool-progress-${id}`)).toBeNull();
  });

  it("toggles the tool timeline on click", () => {
    const id = "r-3";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "完成",
          toolCalls: [{ tool: "tablex_inspect", status: "ok", summary: "扫描空值" }],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    expect(screen.queryByTestId(`tool-timeline-${id}`)).toBeNull();
    fireEvent.click(screen.getByTestId(`tool-progress-toggle-${id}`));
    expect(screen.getByTestId(`tool-timeline-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`tool-timeline-${id}`).textContent).toContain("tablex_inspect");
  });
});

describe("S. Lazy load older", () => {
  it("selectSession loads latest 20 with has_more + oldest_index from API", async () => {
    mockedApi.getSession.mockResolvedValueOnce({
      session_id: "sid",
      title: "test",
      updated_at: "2026-01-01T00:00:00Z",
      message_count: 30,
      last_user_msg: "first user",
      messages: Array.from({ length: 10 }, (_, i) => ({
        role: i % 2 === 0 ? "user" : "assistant",
        content: `msg-${i + 20}`,
      })),
      output_ids: [],
      has_more: true,
      oldest_index: 20,
      total_messages: 30,
    });
    render(<App />);
    await useAppStore.getState().selectSession("sid");
    await waitFor(() => expect(mockedApi.getSession).toHaveBeenCalledWith("sid", expect.objectContaining({ limit: 20 })));
    const s = useAppStore.getState();
    expect(s.messages.length).toBe(10);
    expect(s.sessionHasMore["sid"]).toBe(true);
    expect(s.oldestLoadedIndexBySession["sid"]).toBe(20);
  });

  it("scrolling to top triggers loadOlderMessages with before_index and prepends messages", async () => {
    const sid = "lazy-sess";
    const olderMessages = Array.from({ length: 10 }, (_, i) => ({
      role: i % 2 === 0 ? "user" : "assistant",
      content: `msg-${i + 10}`,
    }));

    render(<App />);
    await waitFor(() => useAppStore.getState().status !== "uploading");

    const initialMessages = Array.from({ length: 20 }, (_, i) => ({
      id: `${sid}-${i + 20}`,
      role: i % 2 === 0 ? "user" : "assistant",
      content: `msg-${i + 20}`,
      timestamp: Date.now(),
    })) as any[];

    useAppStore.setState({
      currentSessionId: sid,
      messages: initialMessages,
      sessionHasMore: { [sid]: true },
      oldestLoadedIndexBySession: { [sid]: 20 },
    } as Partial<typeof useAppStore.getState>);

    mockedApi.getSession.mockResolvedValueOnce({
      session_id: sid,
      title: "test",
      updated_at: "2026-01-01T00:00:00Z",
      message_count: 30,
      last_user_msg: "",
      messages: olderMessages,
      output_ids: [],
      has_more: false,
      oldest_index: 10,
      total_messages: 30,
    });

    const scrollEl = await screen.findByTestId("chat-history");
    Object.defineProperty(scrollEl, "scrollTop", { value: 0, configurable: true });
    Object.defineProperty(scrollEl, "scrollHeight", { value: 1000, configurable: true });
    fireEvent.scroll(scrollEl);

    await waitFor(() =>
      expect(mockedApi.getSession).toHaveBeenCalledWith(sid, expect.objectContaining({ limit: 20, beforeIndex: 20 })),
    );
    await waitFor(() => expect(useAppStore.getState().messages.length).toBe(30));
    expect(useAppStore.getState().sessionHasMore[sid]).toBe(false);
  });
});