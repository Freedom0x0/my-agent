import { FileTextOutlined } from "@ant-design/icons";
import { useAppStore } from "../../hooks/useAppStore";

type Props = {
  fileId: string;
};

export function FileLinkChip({ fileId }: Props) {
  const sessionId = useAppStore((s) => s.currentSessionId);
  const tabs = useAppStore((s) => (sessionId ? s.tabsBySession[sessionId] ?? [] : []));
  const setActiveTab = useAppStore((s) => s.setActiveTab);

  const tab = tabs.find((t) => t.kind === "file" && t.refId === fileId);
  const label = tab?.fileName ?? `${fileId.slice(0, 8)}…`;
  const disabled = !tab || !sessionId;

  const handleClick = () => {
    if (!sessionId || !tab) return;
    setActiveTab(sessionId, tab.id);
  };

  return (
    <button
      type="button"
      className="file-link-chip"
      data-testid="file-link-chip"
      onClick={handleClick}
      disabled={disabled}
    >
      <FileTextOutlined />
      <span>{label}</span>
    </button>
  );
}