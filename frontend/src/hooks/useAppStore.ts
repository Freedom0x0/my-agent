import { create } from "zustand";
import { persist } from "zustand/middleware";

import { api, ApiError } from "../api/httpClient";
import {
  makeUserFacingError,
  mapChatResponseToAssistantMessage,
  mapSessionMessages,
  mapUploadResponse,
} from "../api/mappers";
import { parseWorkbook } from "./useSpreadsheet";
import type {
  ChatMessage,
  FileItem,
  PreviewTarget,
  SessionSummary,
  Tab,
  WorkflowState,
} from "../domain/workflow";
import {
  newSessionId,
  newTabId,
  DEFAULT_SIDER_WIDTH,
  DEFAULT_PREVIEW_WIDTH,
  SIDER_MIN,
  SIDER_MAX,
  PREVIEW_MIN,
  PREVIEW_MAX,
} from "../domain/workflow";

const SESSION_KEY = "tablex.current_session_id";

function newMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `m-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

type Actions = {
  // Sidebar
  loadSessions: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  createSession: () => string;
  removeSessionLocal: (id: string) => void;

  // Uploads
  uploadFile: (file: File) => Promise<void>;
  removeFile: (fileId: string) => void;

  // Chat
  sendMessage: (text: string) => Promise<void>;

  // Previewer / Tabs
  setActivePreview: (target: PreviewTarget | null) => void;
  showOutput: (outputId: string) => void;
  showFile: (fileId: string) => void;
  addTab: (sessionId: string, tab: Omit<Tab, "id" | "openedAt">) => string;
  removeTab: (sessionId: string, tabId: string) => void;
  setActiveTab: (sessionId: string, tabId: string) => void;

  // Streaming
  appendStream: (token: string) => void;
  finishStream: () => void;
  abortStream: () => void;

  // Panels
  setPanelWidth: (side: "sider" | "preview", width: number) => void;
  togglePanel: (side: "sider" | "preview") => void;

  // Error
  clearError: () => void;
};

const initial: WorkflowState = {
  sessions: [],
  sessionsLoading: false,
  currentSessionId: null,
  status: "idle",
  files: [],
  messages: [],
  outputIds: [],
  panel: {
    siderWidth: DEFAULT_SIDER_WIDTH,
    previewWidth: DEFAULT_PREVIEW_WIDTH,
    siderCollapsed: false,
    previewCollapsed: false,
  },
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
};

function tabToPreview(t: Tab): PreviewTarget {
  return t.kind === "file" ? { kind: "file", fileId: t.refId } : { kind: "output", outputId: t.refId };
}

export const useAppStore = create<WorkflowState & Actions>()(
  persist(
    (set, get) => ({
      ...initial,

      loadSessions: async () => {
        set({ sessionsLoading: true });
        try {
          const summaries = await api.listSessions();
          const mapped: SessionSummary[] = summaries.map((s) => ({
            sessionId: s.session_id,
            title: s.title,
            updatedAt: s.updated_at,
            messageCount: s.message_count,
            lastUserMsg: s.last_user_msg,
          }));
          set({ sessions: mapped, sessionsLoading: false });
        } catch {
          set({ sessionsLoading: false });
        }
      },

      selectSession: async (id: string) => {
        const tabs = get().tabsBySession[id] ?? [];
        const activeId = get().activeTabBySession[id] ?? null;
        const activeTab = activeId ? tabs.find((t) => t.id === activeId) ?? null : null;
        set({
          currentSessionId: id,
          status: "ready",
          files: [],
          messages: [],
          outputIds: [],
          filePreviews: {},
          outputPreviews: {},
          activePreview: activeTab ? tabToPreview(activeTab) : null,
          lastChatSheets: [],
          lastChatOutputId: null,
          previewError: null,
          streamingContent: "",
        });
        localStorage.setItem(SESSION_KEY, id);
        try {
          const detail = await api.getSession(id);
          set({
            outputIds: detail.output_ids ?? [],
            messages: mapSessionMessages(detail.messages ?? []),
          });
        } catch (err) {
          if (err instanceof ApiError) {
            set({ error: makeUserFacingError(err.errorCode, err.message) });
          }
        }
      },

      createSession: () => {
        const id = newSessionId();
        set({
          currentSessionId: id,
          status: "ready",
          files: [],
          messages: [],
          outputIds: [],
          filePreviews: {},
          outputPreviews: {},
          activePreview: null,
          tabsBySession: { ...get().tabsBySession, [id]: [] },
          activeTabBySession: { ...get().activeTabBySession, [id]: "" },
          lastChatSheets: [],
          lastChatOutputId: null,
          previewError: null,
          streamingContent: "",
        });
        localStorage.setItem(SESSION_KEY, id);
        return id;
      },

      removeSessionLocal: (id: string) => {
        const { sessions, currentSessionId, tabsBySession, activeTabBySession } = get();
        const { [id]: _t, ...restTabs } = tabsBySession;
        const { [id]: _a, ...restActive } = activeTabBySession;
        void _t; void _a;
        set({
          sessions: sessions.filter((s) => s.sessionId !== id),
          tabsBySession: restTabs,
          activeTabBySession: restActive,
          ...(currentSessionId === id ? initial : {}),
        });
      },

      uploadFile: async (file: File) => {
        const { currentSessionId } = get();
        if (!currentSessionId) get().createSession();
        const sessionId = get().currentSessionId!;

        set({ status: "uploading", error: null });
        let uploaded: FileItem;
        try {
          const resp = await api.uploadFile(file);
          uploaded = mapUploadResponse(resp);
        } catch (err) {
          const e =
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, errorCode: "network_error", message: "上传失败" });
          set({ status: "error", error: makeUserFacingError(e.errorCode, e.message) });
          return;
        }
        set((s) => ({
          status: "parsing",
          files: [...s.files, uploaded],
        }));

        // Client-side preview (non-blocking failure).
        let preview: WorkflowState["filePreviews"][string] | null = null;
        try {
          const buffer = await file.arrayBuffer();
          preview = parseWorkbook(buffer, file.name);
          set((s) => ({
            status: "ready",
            filePreviews: { ...s.filePreviews, [uploaded.id]: preview! },
          }));
        } catch {
          set({ status: "ready" });
        }

        // Add a tab for this file and activate it.
        const tabId = get().addTab(sessionId, {
          kind: "file",
          refId: uploaded.id,
          fileName: uploaded.name,
        });

        // Persist the file id so chat can attach it (no extra backend call needed;
        // file_ids are sent on the next chat message).
        void sessionId;
        void tabId;
      },

      removeFile: (fileId: string) => {
        set((s) => {
          const { [fileId]: _, ...rest } = s.filePreviews;
          void _;
          return {
            files: s.files.filter((f) => f.id !== fileId),
            filePreviews: rest,
            ...(s.activePreview?.kind === "file" && s.activePreview.fileId === fileId
              ? { activePreview: null }
              : {}),
          };
        });
      },

      sendMessage: async (text: string) => {
        const trimmed = text.trim();
        if (!trimmed) return;
        const s = get();
        if (s.status === "processing" || s.status === "uploading") return;
        if (s.files.length === 0) return;

        const sessionId = s.currentSessionId ?? get().createSession();
        const userMsg: ChatMessage = {
          id: newMessageId(),
          role: "user",
          content: trimmed,
          timestamp: Date.now(),
        };
        const fileIds = s.files.map((f) => f.id);
        set({
          status: "processing",
          messages: [...s.messages, userMsg],
          streamingContent: "",
          error: null,
        });

        try {
          const resp = await api.chat({
            message: trimmed,
            file_ids: fileIds,
            session_id: sessionId,
          });
          if (resp.error_code) {
            set({
              status: "error",
              error: makeUserFacingError(resp.error_code, resp.reply),
              messages: s.messages.filter((m) => m.id !== userMsg.id),
            });
            return;
          }
          const assistantId = newMessageId();
          const assistantMsg = mapChatResponseToAssistantMessage(resp, assistantId);
          const outputId = resp.output_id ?? null;
          const sheets = resp.sheets ?? [];
          set((cur) => ({
            status: "completed",
            messages: [...cur.messages, assistantMsg],
            streamingContent: "",
            outputIds: outputId && !cur.outputIds.includes(outputId)
              ? [...cur.outputIds, outputId]
              : cur.outputIds,
            lastChatSheets: sheets,
            lastChatOutputId: outputId,
          }));

          // Add a tab for the new output (if any) and activate it.
          if (outputId) {
            get().addTab(sessionId, {
              kind: "output",
              refId: outputId,
              fileName: `${outputId}.xlsx`,
            });
            try {
              const buffer = await api.download(outputId);
              const preview = parseWorkbook(buffer, `${outputId}.xlsx`);
              set((cur) => ({
                outputPreviews: { ...cur.outputPreviews, [outputId]: preview },
              }));
            } catch {
              set({ previewError: "结果文件解析失败，请点击下方按钮下载查看" });
            }
          }

          void get().loadSessions();
        } catch (err) {
          const apiErr =
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, errorCode: "network_error", message: "请求失败" });
          set({
            status: "error",
            error: makeUserFacingError(apiErr.errorCode, apiErr.message),
            messages: s.messages.filter((m) => m.id !== userMsg.id),
            streamingContent: "",
          });
        }
      },

      setActivePreview: (target) => {
        set({ activePreview: target });
        // Also keep activeTabBySession in sync.
        const { currentSessionId, tabsBySession, activeTabBySession } = get();
        if (!currentSessionId || !target) return;
        const tabs = tabsBySession[currentSessionId] ?? [];
        const match = tabs.find(
          (t) =>
            (target.kind === "file" && t.kind === "file" && t.refId === target.fileId) ||
            (target.kind === "output" && t.kind === "output" && t.refId === target.outputId),
        );
        if (match) {
          set({ activeTabBySession: { ...activeTabBySession, [currentSessionId]: match.id } });
        }
      },

      showOutput: (outputId) => set({ activePreview: { kind: "output", outputId } }),
      showFile: (fileId) => set({ activePreview: { kind: "file", fileId } }),

      addTab: (sessionId, partial) => {
        const id = newTabId();
        const tab: Tab = { ...partial, id, openedAt: Date.now() };
        set((s) => {
          const existing = s.tabsBySession[sessionId] ?? [];
          const next = [
            ...existing.filter(
              (t) => !(t.kind === tab.kind && t.refId === tab.refId),
            ),
            tab,
          ];
          return {
            tabsBySession: { ...s.tabsBySession, [sessionId]: next },
            activeTabBySession: { ...s.activeTabBySession, [sessionId]: id },
            activePreview: tabToPreview(tab),
          };
        });
        return id;
      },

      removeTab: (sessionId, tabId) => {
        set((s) => {
          const existing = s.tabsBySession[sessionId] ?? [];
          const next = existing.filter((t) => t.id !== tabId);
          const curActive = s.activeTabBySession[sessionId];
          let newActiveId = curActive;
          let newPreview: PreviewTarget | null = s.activePreview;
          if (curActive === tabId || !next.find((t) => t.id === curActive)) {
            const fallback = next[next.length - 1] ?? null;
            newActiveId = fallback?.id ?? "";
            newPreview = fallback ? tabToPreview(fallback) : null;
          }
          return {
            tabsBySession: { ...s.tabsBySession, [sessionId]: next },
            activeTabBySession: { ...s.activeTabBySession, [sessionId]: newActiveId },
            activePreview: newPreview,
          };
        });
      },

      setActiveTab: (sessionId, tabId) => {
        set((s) => {
          const tabs = s.tabsBySession[sessionId] ?? [];
          const tab = tabs.find((t) => t.id === tabId);
          return {
            activeTabBySession: { ...s.activeTabBySession, [sessionId]: tabId },
            activePreview: tab ? tabToPreview(tab) : s.activePreview,
          };
        });
      },

      appendStream: (token) => {
        set((s) => ({ streamingContent: s.streamingContent + token }));
      },
      finishStream: () => set({ streamingContent: "" }),
      abortStream: () => {
        // ponytail: backend does not stream yet; stop rendering more content locally.
        // Add real abort wiring when backend ships SSE.
        set({ status: "ready", streamingContent: "" });
      },

      clearError: () => set({ error: null }),

      setPanelWidth: (side, width) =>
        set((s) => {
          const [min, max] = side === "sider" ? [SIDER_MIN, SIDER_MAX] : [PREVIEW_MIN, PREVIEW_MAX];
          const key = side === "sider" ? "siderWidth" : "previewWidth";
          return { panel: { ...s.panel, [key]: Math.max(min, Math.min(width, max)) } };
        }),

      togglePanel: (side) =>
        set((s) => ({
          panel: {
            ...s.panel,
            [side === "sider" ? "siderCollapsed" : "previewCollapsed"]:
              !s.panel[side === "sider" ? "siderCollapsed" : "previewCollapsed"],
          },
        })),
    }),
    {
      name: "tablex.app",
      partialize: (state) => ({
        currentSessionId: state.currentSessionId,
        panel: state.panel,
        tabsBySession: state.tabsBySession,
        activeTabBySession: state.activeTabBySession,
      }),
    },
  ),
);

// Bootstrap on first mount: restore the last session id from localStorage,
// then ask the backend for the sidebar + current session contents.
export async function bootstrapApp(): Promise<void> {
  const store = useAppStore.getState();
  if (!store.currentSessionId) {
    const stored = typeof localStorage !== "undefined" ? localStorage.getItem(SESSION_KEY) : null;
    if (stored) {
      await store.selectSession(stored);
    }
  } else {
    await store.selectSession(store.currentSessionId);
  }
  await store.loadSessions();
}