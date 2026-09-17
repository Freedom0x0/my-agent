import { useAppStore } from "../../hooks/useAppStore";
import type { ChatMessage } from "../../domain/models";
import { BubbleActions } from "./BubbleActions";
import { MarkdownContent } from "./MarkdownContent";

type Props = {
  message: ChatMessage;
  isStreaming?: boolean;
};

export function AssistantBubble({ message, isStreaming = false }: Props) {
  void isStreaming;
  const knownFileIds = useAppStore((s) => s.files).map((f) => f.id);

  return (
    <div className="assistant-bubble" data-testid={`assistant-bubble-${message.id}`}>
      <div className="assistant-bubble-content">
        <MarkdownContent
          content={message.content}
          sheets={message.sheets ?? []}
          outputId={message.outputId ?? null}
          outputName={message.outputName ?? null}
          knownFileIds={knownFileIds}
        />
      </div>
      <BubbleActions message={message} />
    </div>
  );
}
