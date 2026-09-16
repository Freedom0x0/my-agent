import { create } from "zustand";
import { persist } from "zustand/middleware";

import { chatActions } from "./actions/chat";
import { fileActions } from "./actions/file";
import { panelActions } from "./actions/panel";
import { reactionActions } from "./actions/reactions";
import { sessionActions } from "./actions/session";
import { streamActions } from "./actions/stream";
import { tabActions } from "./actions/tab";
import { initial, SESSION_KEY } from "./state";
import type { Actions, WorkflowState } from "./types";

export const useAppStore = create<WorkflowState & Actions>()(
  persist(
    (set, get) => ({
      ...initial,
      ...sessionActions(set, get),
      ...chatActions(set, get),
      ...panelActions(set, get),
      ...tabActions(set, get),
      ...streamActions(set, get),
      ...fileActions(set, get),
      ...reactionActions(set),
    }),
    {
      name: "tablex.app",
      version: 1,
      migrate: (state) => state,
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
