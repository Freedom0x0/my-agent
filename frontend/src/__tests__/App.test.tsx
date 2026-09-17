import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { api } from "../api/httpClient";
import { useAppStore } from "../hooks/useAppStore";
import type { ChatMessage } from "../domain/workflow";
import { AssistantBubble } from "../components/bubble/AssistantBubble";

// Hoisted so tests below can reference them.
const hoisted = vi.hoisted(() => ({
  sseMock: {
    chatStream: vi.fn(),
    readSseStream: vi.fn(),
  },
  parseWorkbookMock: vi.fn(),
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

vi.mock("../hooks/useSpreadsheet", async () => {
  const actual = await vi.importActual<typeof import("../hooks/useSpreadsheet")>(
    "../hooks/useSpreadsheet",
  );
  // Default: delegate to the real implementation. Tests override with
  // .mockImplementationOnce to simulate parse failures.
  hoisted.parseWorkbookMock.mockImplementation(actual.parseWorkbook);
  return {
    ...actual,
    parseWorkbook: hoisted.parseWorkbookMock,
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
  // Clear call history but keep the default implementation (set in vi.mock
  // factory above) so non-override tests still get the real parseWorkbook.
  hoisted.parseWorkbookMock.mockClear();
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
    fileParseErrors: {},
    tabsBySession: {},
    activeTabBySession: {},
    streamingContent: "",
    streamingMessageId: null,
    streamController: null,
    lastChatToolCalls: [],
    lastChatSheets: [],
    lastChatOutputId: null,
    lastChatOutputName: null,
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

describe("Flat message timeline (R replacement)", () => {
  it("renders 1 text + N ToolCallItems interleaved for an assistant message with tool calls", () => {
    const id = "flat-1";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "已完成",
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
    expect(screen.getByTestId(`assistant-bubble-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`tool-call-toggle-tablex_normalize`)).toBeInTheDocument();
    expect(screen.getByTestId(`tool-call-toggle-tablex_export`)).toBeInTheDocument();
    // default collapsed: body not present
    expect(screen.queryByTestId(`tool-call-body-tablex_normalize`)).toBeNull();
    // open the first one
    fireEvent.click(screen.getByTestId(`tool-call-toggle-tablex_normalize`));
    expect(screen.getByTestId(`tool-call-body-tablex_normalize`)).toBeInTheDocument();
    expect(screen.getByTestId(`tool-call-body-tablex_normalize`).textContent).toContain("统一金额格式");
  });

  it("preserves order across 3 tool calls (interleaved after text bubble)", () => {
    const id = "flat-2";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "开始",
          toolCalls: [
            { tool: "t_alpha", status: "ok", summary: "1" },
            { tool: "t_beta", status: "ok", summary: "2" },
            { tool: "t_gamma", status: "ok", summary: "3" },
          ],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    const chat = document.querySelector(".workspace-chat")!;
    const idxAlpha = chat.textContent!.indexOf("t_alpha");
    const idxBeta = chat.textContent!.indexOf("t_beta");
    const idxGamma = chat.textContent!.indexOf("t_gamma");
    expect(idxAlpha).toBeGreaterThanOrEqual(0);
    expect(idxBeta).toBeGreaterThan(idxAlpha);
    expect(idxGamma).toBeGreaterThan(idxBeta);
  });

  it("renders no text bubble when assistant has toolCalls but empty content", () => {
    const id = "flat-3";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "",
          toolCalls: [{ tool: "t_only", status: "ok", summary: "no text" }],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    expect(screen.queryByTestId(`assistant-bubble-${id}`)).toBeNull();
    expect(screen.getByTestId(`tool-call-toggle-t_only`)).toBeInTheDocument();
  });

  it("user message still renders as a single bubble (no interleaving)", () => {
    const uid = "u-1";
    useAppStore.setState({
      messages: [
        { id: uid, role: "user", content: "hi", timestamp: Date.now() },
      ],
    });
    render(<App />);
    expect(screen.getByTestId(`user-bubble-${uid}`)).toBeInTheDocument();
    expect(screen.queryByText(/tool-call/i)).toBeNull();
  });

  it("ToolCallItem collapses again after second click", () => {
    const id = "flat-4";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "x",
          toolCalls: [{ tool: "t_toggle", status: "ok", summary: "s" }],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    const btn = screen.getByTestId(`tool-call-toggle-t_toggle`);
    fireEvent.click(btn);
    expect(screen.getByTestId(`tool-call-body-t_toggle`)).toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.queryByTestId(`tool-call-body-t_toggle`)).toBeNull();
  });

  it("renders SheetLinkChip in ToolCallItem body when outputName present", () => {
    const id = "flat-5";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "完成",
          toolCalls: [
            { tool: "t_export", status: "ok", summary: "导出", outputId: "out-1", outputName: "结果表" },
          ],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    fireEvent.click(screen.getByTestId(`tool-call-toggle-t_export`));
    expect(screen.getByTestId("sheet-link-chip")).toBeInTheDocument();
  });

  it("streams new tool_end events as additional ToolCallItems in the timeline", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());

    render(<App />);

    await useAppStore.getState().uploadFile(
      new File(["x"], "sample.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());

    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "tool_start", name: "tablex_normalize", id: "tu-1" });
        onEvent({
          type: "tool_end",
          name: "tablex_normalize",
          summary: "统一金额",
          status: "ok",
          output_id: null,
        });
        onEvent({ type: "text", delta: "ok" });
        onEvent({
          type: "done",
          reply: "ok",
          tool_calls: [{ tool: "tablex_normalize", status: "ok", summary: "统一金额" }],
          output_id: null,
          sheets: [],
        });
      },
    );

    await useAppStore.getState().sendMessage("hi");
    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));

    const last = useAppStore.getState().messages.at(-1);
    expect(last?.toolCalls?.[0]?.tool).toBe("tablex_normalize");
    expect(await screen.findByTestId(`tool-call-toggle-tablex_normalize`)).toBeInTheDocument();
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

describe("T. Output business-friendly (output_name)", () => {
  const fileId = "abc1234567890abcdef1234567890abc"; // 32 chars (test stub)

  function seed(opts: {
    file?: boolean;
    tabOutput?: { id: string; outputName: string };
    message: { id?: string; content: string; outputName?: string | null; sheets?: string[] };
  }) {
    const sid = "s-chip";
    useAppStore.setState({
      currentSessionId: sid,
      files: opts.file
        ? [
            {
              id: fileId,
              name: "source.xlsx",
              sizeBytes: 1024,
              sheets: [{ ref: `${fileId}::明细`, displayName: "明细", rowCount: 1, columnCount: 1, issues: [], columns: [] }],
            },
          ]
        : [],
      tabsBySession: {
        [sid]: [
          ...(opts.file
            ? [{ id: "tab-file-1", kind: "file", refId: fileId, fileName: "source.xlsx", openedAt: Date.now() }]
            : []),
          ...(opts.tabOutput
            ? [{ id: opts.tabOutput.id, kind: "output", refId: "oid-1", fileName: opts.tabOutput.outputName, outputName: opts.tabOutput.outputName, openedAt: Date.now() }]
            : []),
        ],
      },
      activeTabBySession: { [sid]: opts.tabOutput ? opts.tabOutput.id : "tab-file-1" },
      messages: [
        {
          id: opts.message.id ?? "chip-msg",
          role: "assistant",
          content: opts.message.content,
          toolCalls: [],
          outputName: opts.message.outputName ?? null,
          sheets: opts.message.sheets ?? [],
          timestamp: Date.now(),
        } as ChatMessage,
      ],
    } as Partial<typeof useAppStore.getState>);
  }

  it("MarkdownContent renders outputName as SheetLinkChip", () => {
    seed({ message: { content: "已生成 按部门拆分", outputName: "按部门拆分" } });
    render(<AssistantBubble message={useAppStore.getState().messages[0]} />);
    const chip = screen.getByTestId("sheet-link-chip");
    expect(chip.textContent).toContain("按部门拆分");
  });

  it("SheetLinkChip click switches to a matching tab", () => {
    seed({
      tabOutput: { id: "tab-out-1", outputName: "按部门拆分" },
      message: { content: "按部门拆分", outputName: "按部门拆分" },
    });
    render(<AssistantBubble message={useAppStore.getState().messages[0]} />);
    fireEvent.click(screen.getByTestId("sheet-link-chip"));
    expect(useAppStore.getState().activeTabBySession["s-chip"]).toBe("tab-out-1");
  });

  it("SheetLinkChip click creates a new tab when none exists", () => {
    seed({ message: { content: "新结果", outputName: "新结果" } });
    render(<AssistantBubble message={useAppStore.getState().messages[0]} />);
    const sid = "s-chip";
    const before = useAppStore.getState().tabsBySession[sid].length;
    fireEvent.click(screen.getByTestId("sheet-link-chip"));
    const tabs = useAppStore.getState().tabsBySession[sid];
    expect(tabs.length).toBe(before + 1);
    const created = tabs[tabs.length - 1];
    expect(created.kind).toBe("output");
    expect(created.fileName).toBe("新结果");
    expect(useAppStore.getState().activeTabBySession[sid]).toBe(created.id);
  });

  it("FileLinkChip is rendered and enabled for uploaded file_id", () => {
    seed({ file: true, message: { content: `数据源 ${fileId}` } });
    render(<AssistantBubble message={useAppStore.getState().messages[0]} />);
    const chip = screen.getByTestId("file-link-chip");
    expect(chip).not.toBeDisabled();
    fireEvent.click(chip);
    expect(useAppStore.getState().activeTabBySession["s-chip"]).toBe("tab-file-1");
  });

  it("FileLinkChip is not rendered for unknown file_id (avoids false positives)", () => {
    const orphan = "ffffffffffffffffffffffffffffffff";
    seed({ message: { id: "orphan-msg", content: `未知文件 ${orphan}` } });
    render(<AssistantBubble message={useAppStore.getState().messages[0]} />);
    expect(screen.queryByTestId("file-link-chip")).toBeNull();
  });

  it("MarkdownContent still renders the legacy #sheet: link when sheets array is present", () => {
    seed({ message: { content: "结果是 清洗后数据", sheets: ["清洗后数据"] } });
    render(<AssistantBubble message={useAppStore.getState().messages[0]} />);
    expect(screen.getByTestId("sheet-link")).toBeInTheDocument();
  });

  it("MarkdownContent renders SheetLinkChip with antd icon", () => {
    seed({ message: { content: "按部门拆分", outputName: "按部门拆分" } });
    render(<AssistantBubble message={useAppStore.getState().messages[0]} />);
    const chip = screen.getByTestId("sheet-link-chip");
    expect(chip.querySelector(".anticon")).toBeInTheDocument();
  });

  it("tool_end event with output_name adds an output tab and stores lastChatOutputName", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    await useAppStore.getState().uploadFile(
      new File(["x"], "sample.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
    );
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());

    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "tool_start", name: "tablex_export", id: "tu-1" });
        onEvent({
          type: "tool_end",
          name: "tablex_export",
          summary: "导出",
          status: "ok",
          output_id: "out-xyz",
          output_name: "清洗后数据",
        });
        onEvent({
          type: "done",
          reply: "ok",
          tool_calls: [{ tool: "tablex_export", status: "ok", summary: "导出", output_id: "out-xyz", output_name: "清洗后数据" }],
          output_id: "out-xyz",
          output_name: "清洗后数据",
          sheets: ["清洗后数据"],
        });
      },
    );

    await useAppStore.getState().sendMessage("清洗");
    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));

    const sid = useAppStore.getState().currentSessionId!;
    const tabs = useAppStore.getState().tabsBySession[sid];
    const outputTabs = tabs.filter((t) => t.kind === "output");
    expect(outputTabs.some((t) => t.fileName === "清洗后数据")).toBe(true);
    expect(outputTabs.some((t) => t.outputName === "清洗后数据")).toBe(true);
    expect(useAppStore.getState().lastChatOutputName).toBe("清洗后数据");
  });

  it("done event records outputName on the assistant message", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    await useAppStore.getState().uploadFile(
      new File(["x"], "sample.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
    );
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());

    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "text", delta: "已生成" });
        onEvent({
          type: "done",
          reply: "已生成 部门结果",
          tool_calls: [],
          output_id: "out-2",
          output_name: "部门结果",
          sheets: ["部门结果"],
        });
      },
    );

    await useAppStore.getState().sendMessage("hi");
    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));

    const last = useAppStore.getState().messages.at(-1);
    expect(last?.role).toBe("assistant");
    expect(last?.outputName).toBe("部门结果");
  });

  it("Tab type carries outputName field when created with addTab", () => {
    const sid = "s-addtab";
    useAppStore.setState({
      currentSessionId: sid,
      tabsBySession: { [sid]: [] },
      activeTabBySession: { [sid]: "" },
    } as Partial<typeof useAppStore.getState>);
    const id = useAppStore.getState().addTab(sid, {
      kind: "output",
      refId: "rid-1",
      fileName: "按部门",
      outputName: "按部门",
    });
    const tab = useAppStore.getState().tabsBySession[sid].find((t) => t.id === id);
    expect(tab?.outputName).toBe("按部门");
    expect(tab?.fileName).toBe("按部门");
  });
});

describe("U. Previewer parse failure surface", () => {
  it("shows 解析失败 + retry button when parseWorkbook throws, instead of 正在解析", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    hoisted.parseWorkbookMock.mockImplementationOnce(() => {
      throw new Error("无法预览该文件格式");
    });

    render(<App />);

    const file = new File(["not-a-real-xlsx"], "broken.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await useAppStore.getState().uploadFile(file);

    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());
    await waitFor(() => expect(useAppStore.getState().status).toBe("ready"));

    const errBlock = await screen.findByTestId("previewer-error");
    expect(errBlock).toBeInTheDocument();
    expect(errBlock.textContent).toContain("解析失败");
    expect(errBlock.textContent).toContain("无法预览该文件格式");

    const retry = screen.getByTestId("previewer-error-retry");
    expect(retry).toBeInTheDocument();
    expect(retry.textContent).toBe("重试");

    expect(screen.queryByText("正在解析该文件")).toBeNull();

    const sid = useAppStore.getState().currentSessionId!;
    const fileId = useAppStore.getState().files[0].id;
    expect(useAppStore.getState().fileParseErrors[fileId]).toBe("无法预览该文件格式");
    expect(useAppStore.getState().tabsBySession[sid][0].refId).toBe(fileId);
  });

  it("clearFileParseError removes the error and falls back to 正在解析", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    hoisted.parseWorkbookMock.mockImplementationOnce(() => {
      throw new Error("boom");
    });

    render(<App />);

    const file = new File(["bad"], "broken.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await useAppStore.getState().uploadFile(file);
    await screen.findByTestId("previewer-error");

    const fileId = useAppStore.getState().files[0].id;
    useAppStore.getState().clearFileParseError(fileId);

    expect(useAppStore.getState().fileParseErrors[fileId]).toBeUndefined();
    await waitFor(() => expect(screen.queryByTestId("previewer-error")).toBeNull());
    expect(screen.getByText(/正在解析该文件/)).toBeInTheDocument();
  });

  it("retry button click clears the error and re-renders 正在解析 placeholder", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    hoisted.parseWorkbookMock.mockImplementationOnce(() => {
      throw new Error("无法预览该文件格式");
    });

    render(<App />);

    await useAppStore.getState().uploadFile(
      new File(["bad"], "broken.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    const errBlock = await screen.findByTestId("previewer-error");

    fireEvent.click(screen.getByTestId("previewer-error-retry"));

    await waitFor(() => expect(errBlock).not.toBeInTheDocument());
    expect(screen.getByText(/正在解析该文件/)).toBeInTheDocument();
  });

  it("successful upload still renders the normal SpreadsheetPreview (no error UI)", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());

    render(<App />);

    await useAppStore.getState().uploadFile(
      new File(["x"], "sample.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }),
    );
    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());

    expect(screen.queryByTestId("previewer-error")).toBeNull();
    expect(screen.getByTestId("spreadsheet-preview")).toBeInTheDocument();
    expect(useAppStore.getState().fileParseErrors).toEqual({});
  });
});