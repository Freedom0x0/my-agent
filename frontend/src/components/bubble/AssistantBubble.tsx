import { LoadingOutlined } from "@ant-design/icons";
import { useShallow } from "zustand/react/shallow";

import { useAppStore } from "../../hooks/useAppStore";
import type { Segment } from "../../domain/models";
import { BubbleActions } from "./BubbleActions";
import { MarkdownContent } from "./MarkdownContent";
import { ToolInline } from "./ToolInline";

type Props = {
  id: string;
};

export function AssistantBubble({ id }: Props) {
  // Per-id selector: the stream only ever replaces the tail message object, so
  // every other bubble keeps its reference and skips re-rendering.
  const message = useAppStore((s) => s.messages.find((m) => m.id === id));
  const knownFileIds = useAppStore(useShallow((s) => s.files.map((f) => f.id)));

  if (!message) return null;

  const segments = message.segments ?? [];

  const renderContent = (): React.ReactNode => {
    if (segments.length > 0) {
      // One path for both live and finished turns — the timeline the user watched
      // stream in stays put when the turn ends.
      return segments.map((seg: Segment, i: number) => {
        if (seg.type === "text") {
          return (
            <MarkdownContent
              key={`s${i}`}
              content={seg.content}
              sheets={message.sheets ?? []}
              outputId={message.outputId ?? null}
              outputName={message.outputName ?? null}
              knownFileIds={knownFileIds}
            />
          );
        }
        return (
          <ToolInline
            key={`s${i}`}
            toolCall={seg.call}
            outputName={seg.outputName ?? null}
          />
        );
      });
    }

    if (message.streaming) {
      return (
        <div className="thinking-indicator" data-testid={`thinking-${id}`}>
          <LoadingOutlined spin />
          <span>思考中…</span>
        </div>
      );
    }

    return (
      <>
        {message.content && (
          <MarkdownContent
            content={message.content}
            sheets={message.sheets ?? []}
            outputId={message.outputId ?? null}
            outputName={message.outputName ?? null}
            knownFileIds={knownFileIds}
          />
        )}
        {(message.toolCalls ?? []).map((tc, i) => (
          <ToolInline key={`t${i}`} toolCall={tc} />
        ))}
      </>
    );
  };

  return (
    <div className="assistant-bubble" data-testid={`assistant-bubble-${message.id}`}>
      <div className="assistant-bubble-content">{renderContent()}</div>
      {!message.streaming && <BubbleActions message={message} />}
    </div>
  );
}