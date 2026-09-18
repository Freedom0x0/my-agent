import { FileTextOutlined } from "@ant-design/icons";
import { useAppStore } from "../../hooks/useAppStore";

type Props = {
  fileId: string;
};

export function FileLinkChip({ fileId }: Props) {
  const sessionId = useAppStore((s) => s.currentSessionId);
  const tabs = useAppStore((s) => (sessionId ? s.tabsBySession[sessionId] ?? [] : []));
  const file = useAppStore((s) => s.files.find((f) => f.id === fileId));
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const addTab = useAppStore((s) => s.addTab);

  const tab = tabs.find((t) => t.kind === "file" && t.refId === fileId);
  const label = tab?.fileName ?? file?.name ?? `${fileId.slice(0, 8)}…`;
  // Only a file this session doesn't know about is truly unopenable.
  const disabled = !sessionId || (!tab && !file);

  const handleClick = () => {
    if (!sessionId) return;
    if (tab) {
      setActiveTab(sessionId, tab.id);
      return;
    }
    // The tab was closed, or this browser never had one — the file still belongs to
    // the session, so reopen it rather than leaving a dead chip behind.
    if (!file) return;
    const newId = addTab(sessionId, {
      kind: "file",
      refId: fileId,
      fileName: file.name,
    });
    setActiveTab(sessionId, newId);
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