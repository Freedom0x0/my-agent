import { useAppStore } from "../../hooks/useAppStore";
import type { ChatMessage, Segment } from "../../domain/models";
import { BubbleActions } from "./BubbleActions";
import { MarkdownContent } from "./MarkdownContent";
import { ToolInline } from "./ToolInline";

type Props = {
  message: ChatMessage;
  isStreaming?: boolean;
};

export function AssistantBubble({ message, isStreaming = false }: Props) {
  void isStreaming;
  const knownFileIds = useAppStore((s) => s.files).map((f) => f.id);
  const segments = message.segments;

  const renderContent = (): React.ReactNode => {
    if (segments && segments.length > 0) {
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
      <BubbleActions message={message} />
    </div>
  );
}
