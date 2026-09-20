import { ApiError, api } from "../../../api/httpClient";
import { makeUserFacingError, mapSessionMessages, mapUploadResponse } from "../../../api/mappers";
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

export const SESSION_PAGE_LIMIT = 20;

export function sessionActions(set: Set, get: Get): Pick<Actions, "loadSessions" | "selectSession" | "createSession" | "removeSessionLocal" | "loadOlderMessages"> {
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
        messageReactions: {},
        graph: null,
        graphStage: null,
        selectedNodeId: null,
      });
      localStorage.setItem(SESSION_KEY, id);
      try {
        const detail = await api.getSession(id, { limit: SESSION_PAGE_LIMIT });
        const total = detail.total_messages ?? detail.messages.length;
        const oldestIndex = detail.oldest_index ?? Math.max(0, total - detail.messages.length);
        const mapped = mapSessionMessages(detail.messages, id, oldestIndex);
        set({
          outputIds: detail.output_ids ?? [],
          messages: mapped,
          // Files belong to the conversation — restore them so the sheet list and
          // previews come back with the history instead of needing a re-upload.
          files: (detail.files ?? []).map(mapUploadResponse),
          sessionHasMore: { ...get().sessionHasMore, [id]: detail.has_more ?? false },
          oldestLoadedIndexBySession: { ...get().oldestLoadedIndexBySession, [id]: oldestIndex },
        });
      } catch (err) {
        if (err instanceof ApiError) {
          set({ error: makeUserFacingError(err.errorCode, err.message) });
        }
      }
      // Not awaited: the transcript is what the user came for, the graph can land
      // a moment later. Guarded inside against a session switch racing it.
      void get().loadWorkflow(id);
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
        messageReactions: {},
        graph: null,
        graphStage: null,
        selectedNodeId: null,
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

    loadOlderMessages: async () => {
      const s = get();
      const sid = s.currentSessionId;
      if (!sid || s.sessionLoadingOlder) return;
      if (!(s.sessionHasMore[sid] ?? false)) return;
      const oldestIdx = s.oldestLoadedIndexBySession[sid] ?? 0;
      set({ sessionLoadingOlder: true });
      try {
        const detail = await api.getSession(sid, {
          limit: SESSION_PAGE_LIMIT,
          beforeIndex: oldestIdx,
        });
        const total = detail.total_messages ?? detail.messages.length;
        const newOldestIndex = detail.oldest_index ?? Math.max(0, total - detail.messages.length);
        const mapped = mapSessionMessages(detail.messages, sid, newOldestIndex);
        set((cur) => ({
          messages: [...mapped, ...cur.messages],
          sessionHasMore: { ...cur.sessionHasMore, [sid]: detail.has_more ?? false },
          oldestLoadedIndexBySession: { ...cur.oldestLoadedIndexBySession, [sid]: newOldestIndex },
          sessionLoadingOlder: false,
        }));
      } catch (err) {
        set({ sessionLoadingOlder: false });
        if (err instanceof ApiError) {
          set({ error: makeUserFacingError(err.errorCode, err.message) });
        }
      }
    },
  };
}