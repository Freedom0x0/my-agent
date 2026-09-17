import { FileExcelOutlined } from "@ant-design/icons";
import { useAppStore } from "../../hooks/useAppStore";

type Props = {
  outputName: string;
};

export function SheetLinkChip({ outputName }: Props) {
  const sessionId = useAppStore((s) => s.currentSessionId);
  const tabs = useAppStore((s) => (sessionId ? s.tabsBySession[sessionId] ?? [] : []));
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const addTab = useAppStore((s) => s.addTab);

  const tab = tabs.find((t) => t.kind === "output" && t.fileName === outputName);

  const handleClick = () => {
    if (!sessionId) return;
    if (tab) {
      setActiveTab(sessionId, tab.id);
    } else {
      const newId = addTab(sessionId, {
        kind: "output",
        fileName: outputName,
        outputName,
        refId: "",
      });
      setActiveTab(sessionId, newId);
    }
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