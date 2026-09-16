import { newTabId } from "../../../domain/workflow";
import type { PreviewTarget, Tab } from "../../../domain/workflow";
import { tabToPreview } from "../types";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function tabActions(set: Set, _get: Get): Pick<Actions, "addTab" | "addEmptyTab" | "removeTab" | "setActiveTab" | "setActivePreview" | "showOutput" | "showFile"> {
  return {
    setActivePreview: (target) => {
      set({ activePreview: target });
      // Also keep activeTabBySession in sync.
      const { currentSessionId, tabsBySession, activeTabBySession } = _get();
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

    addEmptyTab: (sessionId) => {
      const id = newTabId();
      const tab: Tab = { id, kind: "file", refId: "", fileName: "新文件", openedAt: Date.now() };
      set((s) => {
        const existing = s.tabsBySession[sessionId] ?? [];
        return {
          tabsBySession: { ...s.tabsBySession, [sessionId]: [...existing, tab] },
          activeTabBySession: { ...s.activeTabBySession, [sessionId]: id },
          activePreview: null,
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
  };
}
