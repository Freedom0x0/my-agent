import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { api } from "../api/httpClient";
import { useAppStore } from "../hooks/useAppStore";

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

const sampleChatResponse = () => ({
  reply: "处理完成，文件 = 清洗后数据",
  tool_calls: [
    { tool: "tablex_normalize", status: "ok", summary: "统一金额格式" },
    { tool: "tablex_export", status: "ok", summary: "导出结果", output_id: "out-1" },
  ],
  output_id: "out-1",
  sheets: ["清洗后数据"],
  session_id: "sess-1",
  error_code: null,
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
    mockedApi.chat.mockResolvedValueOnce(sampleChatResponse());

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

    await waitFor(() => expect(mockedApi.chat).toHaveBeenCalled());

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