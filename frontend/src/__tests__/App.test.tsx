import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "@testing-library/react";

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
      // No graph by default — the canvas renders its empty state.
      getWorkflow: vi.fn().mockRejectedValue(new Error("workflow_not_found")),
      downloadUrl: vi.fn((id: string) => `/api/outputs/${id}`),
      download: vi.fn().mockRejectedValue(new Error("not mocked")),
      downloadUploadedFile: vi.fn().mockRejectedValue(new Error("not mocked")),
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
  getWorkflow: ReturnType<typeof vi.fn>;
  downloadUrl: ReturnType<typeof vi.fn>;
  download: ReturnType<typeof vi.fn>;
  downloadUploadedFile: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.clear();
  }
  mockedApi.listSessions.mockResolvedValue([]);
  mockedApi.getWorkflow.mockRejectedValue(new Error("workflow_not_found"));
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
    previewErrors: {},
    tabsBySession: {},
    activeTabBySession: {},
    streamingMessageId: null,
    streamController: null,
    lastChatSheets: [],
    lastChatOutputId: null,
    lastChatOutputName: null,
    error: null,
    graph: null,
    graphStage: null,
    selectedNodeId: null,
    workspaceView: "chat",
    rightPanel: "file",
    chatUnread: false,
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

  it("keeps the streamed timeline identical when the turn ends", async () => {
    render(<App />);
    // bootstrapApp() re-selects the session on mount and clears files — let it settle
    // before uploading, or sendMessage bails on an empty file list.
    await waitFor(() => expect(mockedApi.listSessions).toHaveBeenCalled());
    await setupWithFile();
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });

    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "text", delta: "先看一下" });
        onEvent({ type: "tool_start", name: "tablex_export", id: "tu-9" });
        onEvent({
          type: "tool_end",
          id: "tu-9",
          name: "tablex_export",
          summary: "导出结果",
          status: "ok",
          output_id: null,
          output_name: null,
        });
        await held;
        onEvent({
          type: "done",
          reply: "先看一下",
          tool_calls: [],
          output_id: null,
          sheets: [],
        });
      },
    );

    const sendPromise = useAppStore.getState().sendMessage("导出");

    // Mid-stream: the turn is still open and the bubble already shows the timeline.
    await waitFor(() => {
      expect(useAppStore.getState().messages.at(-1)?.streaming).toBe(true);
    });
    const streamingId = useAppStore.getState().streamingMessageId!;
    await waitFor(() =>
      expect(screen.getByTestId(`assistant-bubble-${streamingId}`)).toBeInTheDocument(),
    );
    const contentOf = () =>
      screen.getByTestId(`assistant-bubble-${streamingId}`).querySelector(
        ".assistant-bubble-content",
      )?.innerHTML;
    const duringHtml = contentOf();
    expect(duringHtml).toContain("tablex_export");
    expect(duringHtml).toContain("先看一下");

    release();
    await sendPromise;

    // Same bubble id, same content DOM — the turn ending does not reflow the timeline.
    expect(useAppStore.getState().streamingMessageId).toBeNull();
    expect(contentOf()).toBe(duringHtml);
  });

  it("lands text deltas as one text segment on the streaming message", async () => {
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

    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));
    const last = useAppStore.getState().messages.at(-1);
    expect(last?.role).toBe("assistant");
    expect(last?.streaming).toBe(false);
    // Same message the user watched stream in — not a replacement built at the end.
    expect(last?.segments).toEqual([{ type: "text", content: "你好，世界" }]);
    expect(last?.content).toBe("你好，世界");
  });

  it("interleaves tool calls with text in arrival order", async () => {
    await setupWithFile();
    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "text", delta: "先看一下" });
        onEvent({ type: "tool_start", name: "tablex_normalize", id: "tu-1" });
        onEvent({
          type: "tool_end",
          id: "tu-1",
          name: "tablex_normalize",
          summary: "统一金额格式",
          status: "ok",
          output_id: null,
        });
        onEvent({ type: "text", delta: "done" });
        onEvent({
          type: "done",
          reply: "先看一下done",
          tool_calls: [],
          output_id: null,
          sheets: [],
        });
      },
    );

    await useAppStore.getState().sendMessage("检查");

    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));
    const last = useAppStore.getState().messages.at(-1);
    expect(last?.segments).toEqual([
      { type: "text", content: "先看一下" },
      {
        type: "tool",
        call: {
          tool: "tablex_normalize",
          id: "tu-1",
          status: "ok",
          summary: "统一金额格式",
          outputId: null,
          outputName: null,
        },
        outputName: null,
      },
      { type: "text", content: "done" },
    ]);
  });

  it("shows a running tool call before its result arrives", async () => {
    await setupWithFile();
    let midStream: ChatMessage | undefined;
    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "tool_start", name: "tablex_export", id: "tu-9" });
        midStream = useAppStore.getState().messages.at(-1);
        onEvent({
          type: "tool_end",
          id: "tu-9",
          name: "tablex_export",
          summary: "导出结果",
          status: "ok",
          output_id: null,
        });
        onEvent({ type: "done", reply: "", tool_calls: [], output_id: null, sheets: [] });
      },
    );

    await useAppStore.getState().sendMessage("导出");

    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));
    expect(midStream?.streaming).toBe(true);
    expect(midStream?.segments).toEqual([
      {
        type: "tool",
        call: { tool: "tablex_export", id: "tu-9", status: "running", summary: "" },
      },
    ]);
  });

  it("marks a failed tool call as error", async () => {
    await setupWithFile();
    hoisted.sseMock.readSseStream.mockImplementationOnce(
      async (_reader, onEvent) => {
        onEvent({ type: "tool_start", name: "tablex_pivot", id: "tu-3" });
        onEvent({
          type: "tool_end",
          id: "tu-3",
          name: "tablex_pivot",
          summary: "参数校验失败",
          status: "error",
          output_id: null,
        });
        onEvent({ type: "done", reply: "", tool_calls: [], output_id: null, sheets: [] });
      },
    );

    await useAppStore.getState().sendMessage("透视");

    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));
    const seg = useAppStore.getState().messages.at(-1)?.segments?.[0];
    expect(seg?.type === "tool" && seg.call.status).toBe("error");
  });

  it("abortStream keeps the partial timeline instead of wiping it", async () => {
    await setupWithFile();
    let capturedSignal: AbortSignal | undefined;
    hoisted.sseMock.chatStream.mockImplementationOnce(
      async (_payload, signal) => {
        capturedSignal = signal;
        return {} as ReadableStreamDefaultReader<Uint8Array>;
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
    expect(useAppStore.getState().streamController).toBeNull();
    const last = useAppStore.getState().messages.at(-1);
    expect(last?.streaming).toBe(false);
    expect(last?.segments).toEqual([{ type: "text", content: "partial " }]);
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

describe("Inline tool in bubble (segments)", () => {
  it("renders 1 bubble with text + tool inlines interleaved when segments present", () => {
    const id = "seg-1";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "",
          segments: [
            { type: "text", content: "已完成" },
            {
              type: "tool",
              call: { tool: "tablex_normalize", status: "ok", summary: "统一金额格式" },
              outputName: null,
            },
            {
              type: "tool",
              call: { tool: "tablex_export", status: "ok", summary: "导出结果", outputId: "out-1" },
              outputName: "清洗后数据",
            },
          ],
          toolCalls: [],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    const bubble = screen.getByTestId(`assistant-bubble-${id}`);
    expect(bubble).toBeInTheDocument();
    expect(bubble.querySelectorAll(".tool-inline")).toHaveLength(2);
    expect(screen.getByTestId("tool-inline-tablex_normalize")).toBeInTheDocument();
    expect(screen.getByTestId("tool-inline-tablex_export")).toBeInTheDocument();
    expect(bubble.textContent).toContain("已完成");
    expect(bubble.textContent).toContain("tablex_normalize");
    expect(bubble.textContent).toContain("tablex_export");
  });

  it("renders SheetLinkChip inline next to tool that has outputName", () => {
    const id = "seg-2";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "",
          segments: [
            {
              type: "tool",
              call: { tool: "tablex_export", status: "ok", summary: "导出", outputId: "out-1" },
              outputName: "结果表",
            },
          ],
          toolCalls: [],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    expect(screen.getByTestId("tool-inline-tablex_export")).toBeInTheDocument();
    const chip = screen.getByTestId("sheet-link-chip");
    expect(chip).toBeInTheDocument();
    expect(chip.textContent).toContain("结果表");
  });

  it("does NOT render SheetLinkChip when tool has no outputName", () => {
    const id = "seg-3";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "",
          segments: [
            {
              type: "tool",
              call: { tool: "tablex_normalize", status: "ok", summary: "1" },
              outputName: null,
            },
          ],
          toolCalls: [],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    expect(screen.getByTestId("tool-inline-tablex_normalize")).toBeInTheDocument();
    expect(screen.queryByTestId("sheet-link-chip")).toBeNull();
  });

  it("falls back to content + toolCalls when segments absent (legacy message)", () => {
    const id = "seg-4";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "旧消息",
          segments: undefined,
          toolCalls: [
            { tool: "t_legacy", status: "ok", summary: "1" },
          ],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    const bubble = screen.getByTestId(`assistant-bubble-${id}`);
    expect(bubble.textContent).toContain("旧消息");
    expect(screen.getByTestId("tool-inline-t_legacy")).toBeInTheDocument();
  });

  it("renders 1 bubble even with empty content + tool (no separate ToolCallItem)", () => {
    const id = "seg-5";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "",
          segments: [
            {
              type: "tool",
              call: { tool: "t_only", status: "ok", summary: "no text" },
              outputName: null,
            },
          ],
          toolCalls: [],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    expect(screen.getByTestId(`assistant-bubble-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId("tool-inline-t_only")).toBeInTheDocument();
    // exactly one bubble rendered (no separate ToolCallItem bubble)
    expect(screen.getAllByTestId(/^assistant-bubble-/).length).toBe(1);
  });

  it("preserves segment order: text -> tool -> text -> tool", () => {
    const id = "seg-6";
    useAppStore.setState({
      messages: [
        {
          id,
          role: "assistant",
          content: "",
          segments: [
            { type: "text", content: "first text" },
            { type: "tool", call: { tool: "t_a", status: "ok", summary: "1" }, outputName: null },
            { type: "text", content: "middle text" },
            { type: "tool", call: { tool: "t_b", status: "ok", summary: "2" }, outputName: null },
          ],
          toolCalls: [],
          outputId: null,
          sheets: [],
          timestamp: Date.now(),
        },
      ],
    });
    render(<App />);
    const bubble = screen.getByTestId(`assistant-bubble-${id}`);
    const txt = bubble.textContent!;
    const idxFirstText = txt.indexOf("first text");
    const idxA = txt.indexOf("t_a");
    const idxMiddleText = txt.indexOf("middle text");
    const idxB = txt.indexOf("t_b");
    expect(idxFirstText).toBeGreaterThanOrEqual(0);
    expect(idxA).toBeGreaterThan(idxFirstText);
    expect(idxMiddleText).toBeGreaterThan(idxA);
    expect(idxB).toBeGreaterThan(idxMiddleText);
  });

  it("user message still renders as a single bubble (no tool inline leakage)", () => {
    const uid = "u-1";
    useAppStore.setState({
      messages: [
        { id: uid, role: "user", content: "hi", timestamp: Date.now() },
      ],
    });
    render(<App />);
    expect(screen.getByTestId(`user-bubble-${uid}`)).toBeInTheDocument();
    expect(screen.queryByTestId(/^tool-inline-/)).toBeNull();
  });

  it("SSE done event with segments stores them on the assistant message", async () => {
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
        onEvent({ type: "text", delta: "处理" });
        onEvent({ type: "tool_start", name: "tablex_normalize", id: "tu-1" });
        onEvent({
          type: "tool_end",
          name: "tablex_normalize",
          summary: "统一金额",
          status: "ok",
          output_id: null,
        });
        onEvent({ type: "text", delta: "完成" });
        onEvent({
          type: "done",
          reply: "处理完成",
          tool_calls: [{ tool: "tablex_normalize", status: "ok", summary: "统一金额" }],
          output_id: null,
          sheets: [],
          segments: [
            { type: "text", content: "处理" },
            {
              type: "tool",
              call: { tool: "tablex_normalize", status: "ok", summary: "统一金额" },
              output_name: null,
            },
            { type: "text", content: "完成" },
          ],
        });
      },
    );

    await useAppStore.getState().sendMessage("hi");
    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));

    const last = useAppStore.getState().messages.at(-1);
    expect(last?.role).toBe("assistant");
    expect(last?.segments).toBeDefined();
    expect(last?.segments?.length).toBe(3);
    expect(last?.segments?.[0]).toEqual({ type: "text", content: "处理" });
    expect(last?.segments?.[1].type).toBe("tool");
    expect(last?.segments?.[2]).toEqual({ type: "text", content: "完成" });

    expect(await screen.findByTestId("tool-inline-tablex_normalize")).toBeInTheDocument();
  });
});

describe("V. Workspace view tabs (会话 / 画布)", () => {
  const graph = {
    nodes: [
      {
        id: "n1",
        seq: 1,
        label: "读取文件",
        tool: "tablex_upload",
        input: { file_id: "f_a" },
        status: "ok" as const,
        output: null,
        duration_ms: null,
        error: null,
        edited: false,
        cached: false,
      },
      {
        id: "n2",
        seq: 2,
        label: "按部门汇总",
        tool: "tablex_group_summary",
        input: { group_by: ["部门"] },
        status: "pending" as const,
        output: null,
        duration_ms: null,
        error: null,
        edited: false,
        cached: false,
      },
    ],
    edges: [{ from_node: "n1", to_node: "n2", to_param: "sheet" }],
  };

  it("carries the shared action bar, opens node detail on click, and flags unread chat", () => {
    useAppStore.setState({ graph, graphStage: "awaiting_approval" });
    render(<App />);

    // Chat is the default view; its scroll container unmounts when the canvas shows.
    expect(screen.getByTestId("chat-history")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("view-tab-canvas"));
    expect(screen.getByTestId("workflow-canvas")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-history")).toBeNull();

    // The action bar + input are siblings of the view body, so both tabs share them.
    expect(screen.getByTestId("flowbar")).toBeInTheDocument();
    expect(screen.getAllByTestId("sender").length).toBeGreaterThan(0);

    // Clicking a node switches the right pane to its detail.
    fireEvent.click(screen.getByTestId("graph-node-n2"));
    expect(screen.getByTestId("panel-tab-node").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("node-detail").textContent).toContain("按部门汇总");

    // The model speaks while the user is on the canvas → the chat tab gets a dot.
    act(() => {
      useAppStore.getState().appendTextDelta("图已生成", { separate: true });
    });
    expect(screen.getByTestId("chat-unread")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("view-tab-chat"));
    expect(screen.queryByTestId("chat-unread")).toBeNull();
    expect(screen.getByTestId("chat-history")).toBeInTheDocument();
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
    /** Set false to model a session whose file tab was closed / never created here. */
    fileTab?: boolean;
    tabOutput?: { id: string; outputName: string };
    message: { id?: string; content: string; outputName?: string | null; sheets?: string[] };
  }) {
    const sid = "s-chip";
    const withFileTab = opts.file && opts.fileTab !== false;
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
          ...(withFileTab
            ? [{ id: "tab-file-1", kind: "file", refId: fileId, fileName: "source.xlsx", openedAt: Date.now() }]
            : []),
          ...(opts.tabOutput
            ? [{ id: opts.tabOutput.id, kind: "output", refId: "oid-1", fileName: opts.tabOutput.outputName, outputName: opts.tabOutput.outputName, openedAt: Date.now() }]
            : []),
        ],
      },
      activeTabBySession: { [sid]: opts.tabOutput ? opts.tabOutput.id : withFileTab ? "tab-file-1" : "" },
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
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);
    const chip = screen.getByTestId("sheet-link-chip");
    expect(chip.textContent).toContain("按部门拆分");
  });

  it("SheetLinkChip click switches to a matching tab", () => {
    seed({
      tabOutput: { id: "tab-out-1", outputName: "按部门拆分" },
      message: { content: "按部门拆分", outputName: "按部门拆分" },
    });
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);
    fireEvent.click(screen.getByTestId("sheet-link-chip"));
    expect(useAppStore.getState().activeTabBySession["s-chip"]).toBe("tab-out-1");
  });

  it("SheetLinkChip click creates a new tab when none exists", () => {
    seed({ message: { content: "新结果", outputName: "新结果" } });
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);
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
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);
    const chip = screen.getByTestId("file-link-chip");
    expect(chip).not.toBeDisabled();
    fireEvent.click(chip);
    expect(useAppStore.getState().activeTabBySession["s-chip"]).toBe("tab-file-1");
  });

  it("FileLinkChip is not rendered for unknown file_id (avoids false positives)", () => {
    const orphan = "ffffffffffffffffffffffffffffffff";
    seed({ message: { id: "orphan-msg", content: `未知文件 ${orphan}` } });
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);
    expect(screen.queryByTestId("file-link-chip")).toBeNull();
  });

  it("FileLinkChip reopens the file when its tab is gone", () => {
    // The file came back with the session, but this browser has no tab for it —
    // closed by the user, or a fresh browser. The chip used to be dead here.
    seed({ file: true, fileTab: false, message: { content: `数据源 ${fileId}` } });
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);

    const chip = screen.getByTestId("file-link-chip");
    expect(chip).not.toBeDisabled();
    // Label comes from the session's file list, not the raw id prefix.
    expect(chip.textContent).toContain("source.xlsx");

    fireEvent.click(chip);

    const sid = "s-chip";
    const tabs = useAppStore.getState().tabsBySession[sid];
    const created = tabs[tabs.length - 1];
    expect(created.kind).toBe("file");
    expect(created.refId).toBe(fileId);
    expect(created.fileName).toBe("source.xlsx");
    expect(useAppStore.getState().activeTabBySession[sid]).toBe(created.id);
  });

  it("MarkdownContent still renders the legacy #sheet: link when sheets array is present", () => {
    seed({ message: { content: "结果是 清洗后数据", sheets: ["清洗后数据"] } });
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);
    expect(screen.getByTestId("sheet-link")).toBeInTheDocument();
  });

  it("MarkdownContent renders SheetLinkChip with antd icon", () => {
    seed({ message: { content: "按部门拆分", outputName: "按部门拆分" } });
    render(<AssistantBubble id={useAppStore.getState().messages[0].id} />);
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
    expect(useAppStore.getState().previewErrors[fileId]).toBe("无法预览该文件格式");
    expect(useAppStore.getState().tabsBySession[sid][0].refId).toBe(fileId);
  });

  it("retry re-fetches the file and renders the preview once it parses", async () => {
    mockedApi.uploadFile.mockResolvedValueOnce(sampleUploadResponse());
    const fakePreview = {
      filename: "broken.xlsx",
      sheets: [{ name: "Sheet1", rows: [["a"]], totalRows: 1, truncated: false }],
    };
    hoisted.parseWorkbookMock.mockImplementationOnce(() => {
      throw new Error("无法预览该文件格式");
    });
    hoisted.parseWorkbookMock.mockReturnValueOnce(fakePreview);
    mockedApi.downloadUploadedFile.mockResolvedValueOnce(new ArrayBuffer(8));

    render(<App />);

    const file = new File(["bad"], "broken.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await useAppStore.getState().uploadFile(file);

    const errBlock = await screen.findByTestId("previewer-error");
    expect(errBlock.textContent).toContain("无法预览该文件格式");

    fireEvent.click(screen.getByTestId("previewer-error-retry"));

    const fileId = useAppStore.getState().files[0].id;
    await waitFor(() => expect(mockedApi.downloadUploadedFile).toHaveBeenCalledWith(fileId));
    await waitFor(() => expect(screen.queryByTestId("previewer-error")).toBeNull());
    expect(useAppStore.getState().filePreviews[fileId]).toEqual(fakePreview);
    expect(screen.getByTestId("spreadsheet-preview")).toBeInTheDocument();
  });

  it("re-fetches a restored tab's preview on open (reload / session switch)", async () => {
    // What a reload leaves behind: the tab list is persisted to local storage, the
    // parsed preview cache is not. Nothing used to fetch it back.
    const fakePreview = {
      filename: "旧文件.xlsx",
      sheets: [{ name: "Sheet1", rows: [["x"]], totalRows: 1, truncated: false }],
    };
    hoisted.parseWorkbookMock.mockReturnValueOnce(fakePreview);
    mockedApi.downloadUploadedFile.mockResolvedValueOnce(new ArrayBuffer(8));
    mockedApi.getSession.mockResolvedValueOnce({
      session_id: "s-reload",
      title: "旧会话",
      updated_at: "",
      message_count: 0,
      last_user_msg: "",
      messages: [],
      output_ids: [],
      files: [],
      has_more: false,
      oldest_index: 0,
      total_messages: 0,
    });

    useAppStore.setState({
      currentSessionId: "s-reload",
      status: "ready",
      tabsBySession: {
        "s-reload": [
          { id: "tab-1", kind: "file", refId: "f-old", fileName: "旧文件.xlsx", openedAt: 1 },
        ],
      },
      activeTabBySession: { "s-reload": "tab-1" },
    });

    render(<App />);

    await waitFor(() => expect(mockedApi.downloadUploadedFile).toHaveBeenCalledWith("f-old"));
    await waitFor(() => expect(screen.getByTestId("spreadsheet-preview")).toBeInTheDocument());
    expect(useAppStore.getState().filePreviews["f-old"]).toEqual(fakePreview);
    expect(screen.queryByTestId("previewer-error")).toBeNull();
  });

  it("fetches an output tab's preview from /api/outputs when it isn't cached", async () => {
    // The other half of the same path: an export result reopened after a reload.
    const fakePreview = {
      filename: "清洗后数据.xlsx",
      sheets: [{ name: "Sheet1", rows: [["a", "b"]], totalRows: 1, truncated: false }],
    };
    hoisted.parseWorkbookMock.mockReturnValueOnce(fakePreview);
    mockedApi.download.mockResolvedValueOnce(new ArrayBuffer(8));
    mockedApi.getSession.mockResolvedValueOnce({
      session_id: "s-out",
      title: "旧会话",
      updated_at: "",
      message_count: 0,
      last_user_msg: "",
      messages: [],
      output_ids: ["out-1"],
      files: [],
      has_more: false,
      oldest_index: 0,
      total_messages: 0,
    });

    useAppStore.setState({
      currentSessionId: "s-out",
      status: "ready",
      tabsBySession: {
        "s-out": [
          {
            id: "tab-out",
            kind: "output",
            refId: "out-1",
            fileName: "清洗后数据",
            outputName: "清洗后数据",
            openedAt: 1,
          },
        ],
      },
      activeTabBySession: { "s-out": "tab-out" },
    });

    render(<App />);

    await waitFor(() => expect(mockedApi.download).toHaveBeenCalledWith("out-1"));
    await waitFor(() => expect(screen.getByTestId("spreadsheet-preview")).toBeInTheDocument());
    expect(useAppStore.getState().outputPreviews["out-1"]).toEqual(fakePreview);
    expect(screen.queryByTestId("previewer-error")).toBeNull();
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
    expect(useAppStore.getState().previewErrors).toEqual({});
  });
});