import { CheckCircleFilled, CloseCircleFilled, LinkOutlined } from "@ant-design/icons";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import ReactMarkdown, { type Components } from "react-markdown";

import { useAppStore } from "../../hooks/useAppStore";
import { FileLinkChip } from "./FileLinkChip";
import { SheetLinkChip } from "./SheetLinkChip";

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

type Props = {
  content: string;
  sheets?: string[];
  outputId?: string | null;
  outputName?: string | null;
  knownFileIds?: string[];
};

function injectLinks(
  raw: string,
  sheets: string[],
  outputName: string | null,
  knownFileIds: string[],
): string {
  let out = raw;
  if (outputName) {
    out = out.replace(
      new RegExp(escapeRegex(outputName), "g"),
      `[${outputName}](#output:${encodeURIComponent(outputName)})`,
    );
  }
  if (sheets.length) {
    const sorted = [...sheets].sort((a, b) => b.length - a.length);
    const re = new RegExp(
      `(?<![一-鿿])(${sorted.map(escapeRegex).join("|")})(?![一-鿿])`,
      "g",
    );
    out = out.replace(re, (name) => `[${name}](#sheet:${encodeURIComponent(name)})`);
  }
  const ids = knownFileIds.filter((id) => /^[a-f0-9]{32}$/.test(id));
  if (ids.length) {
    const re = new RegExp(`(${ids.map(escapeRegex).join("|")})`, "g");
    out = out.replace(re, (id) => `[📄 ${id.slice(0, 8)}…](#file:${id})`);
  }
  return out;
}

function LegacySheetLinkButton({ name }: { name: string }) {
  const showOutput = useAppStore((s) => s.showOutput);
  return (
    <button
      type="button"
      className="sheet-link"
      data-testid="sheet-link"
      onClick={() => showOutput("")}
    >
      {name}
    </button>
  );
}

export function MarkdownContent({
  content,
  sheets = [],
  outputId: _outputId = null,
  outputName = null,
  knownFileIds = [],
}: Props) {
  const injected = injectLinks(content, sheets, outputName, knownFileIds);

  const components: Components = {
    code({ inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || "");
      if (!inline && match) {
        return (
          <SyntaxHighlighter
            language={match[1]}
            style={oneLight}
            PreTag="div"
            customStyle={{ borderRadius: 6, fontSize: 12, margin: "8px 0" }}
          >
            {String(children).replace(/\n$/, "")}
          </SyntaxHighlighter>
        );
      }
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
    a: ({ href, children }: any) => {
      if (typeof href === "string") {
        if (href.startsWith("#output:")) {
          const name = decodeURIComponent(href.slice(8));
          return <SheetLinkChip outputName={name} />;
        }
        if (href.startsWith("#file:")) {
          const fileId = href.slice(6);
          return <FileLinkChip fileId={fileId} />;
        }
        if (href.startsWith("#sheet:")) {
          const name = decodeURIComponent(href.slice(7));
          return <LegacySheetLinkButton name={name} />;
        }
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children} <LinkOutlined style={{ fontSize: 10, marginLeft: 2 }} />
        </a>
      );
    },
  };

  return (
    <div className="markdown-content" data-testid="markdown-content">
      <ReactMarkdown components={components}>{injected}</ReactMarkdown>
    </div>
  );
}

export function ToolStatusIcon({ status }: { status: "ok" | "error" }) {
  return status === "ok" ? (
    <CheckCircleFilled style={{ color: "#52c41a", fontSize: 12 }} />
  ) : (
    <CloseCircleFilled style={{ color: "#f5222d", fontSize: 12 }} />
  );
}