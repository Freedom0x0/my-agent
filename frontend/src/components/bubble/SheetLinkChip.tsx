import { FileExcelOutlined } from "@ant-design/icons";
import { useAppStore } from "../../hooks/useAppStore";
import type { ChatMessage } from "../../domain/models";

type Props = {
  outputName: string;
};

const EMPTY_TABS: never[] = [];

/**
 * The chip only knows the output's *name*; the previewer needs its id. Recover it
 * from the message that produced it — otherwise opening a chip for a tab that isn't
 * around any more (after a reload) would build a tab with no id and spin forever.
 */
function resolveOutputId(messages: ChatMessage[], outputName: string): string {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    for (const seg of m.segments ?? []) {
      if (seg.type === "tool" && (seg.outputName ?? seg.call.outputName) === outputName) {
        return seg.call.outputId ?? "";
      }
    }
    for (const tc of m.toolCalls ?? []) {
      if (tc.outputName === outputName) return tc.outputId ?? "";
    }
  }
  return "";
}

export function SheetLinkChip({ outputName }: Props) {
  const sessionId = useAppStore((s) => s.currentSessionId);
  const tabs = useAppStore((s) =>
    sessionId ? s.tabsBySession[sessionId] ?? EMPTY_TABS : EMPTY_TABS,
  );
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const addTab = useAppStore((s) => s.addTab);

  const tab = tabs.find((t) => t.kind === "output" && t.fileName === outputName);

  const handleClick = () => {
    if (!sessionId) return;
    if (tab) {
      setActiveTab(sessionId, tab.id);
      return;
    }
    const refId = resolveOutputId(useAppStore.getState().messages, outputName);
    const newId = addTab(sessionId, {
      kind: "output",
      fileName: outputName,
      outputName,
      refId,
    });
    setActiveTab(sessionId, newId);
  };

  return (
    <button
      type="button"
      className="sheet-link-chip"
      data-testid="sheet-link-chip"
      onClick={handleClick}
    >
      <FileExcelOutlined />
      <span>{outputName}</span>
    </button>
  );
}