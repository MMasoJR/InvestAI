import type { ChatMessage as ChatMessageType } from "@/types/chat";
import { SourceChip } from "@/components/SourceChip";
import { ToolCallIndicator } from "@/components/ToolCallIndicator";

export function ChatMessage({ message }: { message: ChatMessageType }) {
  if (message.role === "user") {
    return (
      <div className="flex animate-fade-in justify-end">
        <div className="max-w-[75%] rounded-lg border border-gold/30 bg-bg-elevated px-4 py-3 text-ink">
          {message.text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex animate-fade-in justify-start">
      <div className="max-w-[85%] border-l-2 border-gold pl-4">
        <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-gold">
          Assessor
        </div>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2">
            {message.toolCalls.map((tc, i) => (
              <ToolCallIndicator
                key={i}
                name={tc.name}
                input={tc.input}
                result={message.toolResult}
              />
            ))}
          </div>
        )}
        <p className="whitespace-pre-wrap leading-relaxed text-ink">
          {message.text}
          {message.isStreaming && (
            <span className="ml-0.5 inline-block h-4 w-[2px] animate-blink-cursor bg-gold align-middle" />
          )}
        </p>
        {message.sources && message.sources.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.sources.map((source, i) => (
              <SourceChip key={`${source.company_name}-${i}`} source={source} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
