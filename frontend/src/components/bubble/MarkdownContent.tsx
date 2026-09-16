import { CheckCircleFilled, CloseCircleFilled, LinkOutlined } from "@ant-design/icons";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import ReactMarkdown, { type Components } from "react-markdown";

import { useAppStore } from "../../hooks/useAppStore";

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function SheetLinkButton({ name, outputId }: { name: string; outputId: string | null }) {
  const showOutput = useAppStore((s) => s.showOutput);
  if (!outputId) return <span>{name}</span>;
  return (
    <button
      type="button"
      className="sheet-link"
      data-testid="sheet-link"
      onClick={() => showOutput(outputId)}
    >
      {name}
    </button>
  );
}

function injectSheetLinks(raw: string, sheets: string[]): string {
  if (!raw || !sheets?.length) return raw;
  const sorted = [...sheets].sort((a, b) => b.length - a.length);
  const re = new RegExp(`(?<![\\u4e00-\\u9fff])(${sorted.map(escapeRegex).join("|")})(?![\\u4e00-\\u9fff])`, "g");
  return raw.replace(re, (name) => `[${name}](#sheet:${encodeURIComponent(name)})`);
}

type Props = {
  content: string;
  sheets?: string[];
  outputId?: string | null;
};

export function MarkdownContent({ content, sheets = [], outputId = null }: Props) {
  const injected = injectSheetLinks(content, sheets);
  const linkOutputId = outputId;

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
      if (typeof href === "string" && href.startsWith("#sheet:")) {
        const name = decodeURIComponent(href.slice(7));
        return <SheetLinkButton name={name} outputId={linkOutputId} />;
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