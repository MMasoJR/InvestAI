export type Source = {
  company_name: string | null;
  statement_type: string | null;
  period_end: string | null;
  score: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
  isStreaming?: boolean;
  toolCalls?: { name: string; input: Record<string, unknown> }[];
  toolResult?: string;
};

export type StreamEvent =
  | { type: "conversation"; conversation_id: string }
  | { type: "sources"; sources: Source[] }
  | { type: "tool_call"; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; text: string }
  | { type: "token"; text: string }
  | { type: "done" };
