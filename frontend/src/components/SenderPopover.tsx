import { useEffect, useMemo, useState } from "react";

export type Suggestion =
  | { kind: "file"; label: string; value: string }
  | { kind: "command"; label: string; value: string; description?: string };

type Props = {
  value: string;
  onChange: (next: string) => void;
  files: { name: string; id: string }[];
  onPickCommand: (value: string) => void;
};

const COMMANDS: Suggestion[] = [
  { kind: "command", value: "/clear", label: "/clear", description: "清空当前会话消息" },
  { kind: "command", value: "/new", label: "/new", description: "新建会话并切换" },
];

export function SenderPopover({
  value,
  onChange,
  files,
  onPickCommand,
}: Props) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"@" | "/">("@");
  const [query, setQuery] = useState("");
  const [triggerStart, setTriggerStart] = useState<number>(0);

  useEffect(() => {
    const cursor = value.length;
    const before = value.slice(0, cursor);
    const at = before.lastIndexOf("@");
    const slash = before.lastIndexOf("/");
    const wsAt = at <= 0 || /\s/.test(before[at - 1] ?? "");
    const wsSlash = slash <= 0 || /\s/.test(before[slash - 1] ?? "");
    const fileTrigger = at > slash && at >= 0 && wsAt;
    const cmdTrigger = slash > at && slash >= 0 && wsSlash;
    if (fileTrigger) {
      const fragment = before.slice(at + 1);
      if (/\s/.test(fragment)) {
        setOpen(false);
        return;
      }
      setMode("@");
      setQuery(fragment);
      setTriggerStart(at);
      setOpen(true);
      return;
    }
    if (cmdTrigger) {
      const fragment = before.slice(slash + 1);
      if (/\s/.test(fragment)) {
        setOpen(false);
        return;
      }
      setMode("/");
      setQuery(fragment);
      setTriggerStart(slash);
      setOpen(true);
      return;
    }
    setOpen(false);
  }, [value]);

  const options = useMemo<Suggestion[]>(() => {
    if (mode === "/") {
      return COMMANDS.filter((c) => c.value.toLowerCase().includes(query.toLowerCase()));
    }
    return files
      .filter((f) => f.name.toLowerCase().includes(query.toLowerCase()))
      .map((f) => ({ kind: "file", value: f.name, label: f.name }));
  }, [mode, query, files]);

  if (!open || options.length === 0) return null;

  const pick = (s: Suggestion) => {
    const cursor = value.length;
    const before = value.slice(0, triggerStart);
    const after = value.slice(cursor);
    const inserted = s.kind === "file" ? `@${s.value} ` : s.value;
    const next = before + inserted + after;
    onChange(next);
    if (s.kind === "command") onPickCommand(s.value);
    setOpen(false);
  };

  return (
    <div className="sender-popover" data-testid="sender-popover">
      {options.map((o) => (
        <button
          type="button"
          key={o.value}
          className="sender-popover-item"
          onClick={() => pick(o)}
          data-testid="sender-popover-item"
        >
          {o.kind === "command" ? (
            <>
              <b>{o.label}</b>
              {o.description ? <span className="sender-popover-sub">{o.description}</span> : null}
            </>
          ) : (
            <span>📄 {o.label}</span>
          )}
        </button>
      ))}
    </div>
  );
}