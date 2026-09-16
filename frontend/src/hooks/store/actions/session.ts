import { ApiError, api } from "../../../api/httpClient";
import { makeUserFacingError, mapSessionMessages } from "../../../api/mappers";
import { newSessionId } from "../../../domain/workflow";
import type { SessionSummary } from "../../../domain/workflow";
import { SESSION_KEY } from "../state";
import { initial } from "../state";
import { tabToPreview } from "../types";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function sessionActions(set: Set, get: Get): Pick<Actions, "loadSessions" | "selectSession" | "createSession" | "removeSessionLocal"> {
  return {
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
  };
}
