import { createNdjsonParser } from "@/lib/parseStream";
import type { Source, StreamEvent } from "@/types/chat";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type StreamCallbacks = {
  onConversationId: (conversationId: string) => void;
  onSources: (sources: Source[]) => void;
  onToolCall: (name: string, input: Record<string, unknown>) => void;
  onToolResult: (text: string) => void;
  onToken: (text: string) => void;
  onDone: () => void;
  onError: (error: Error) => void;
};

export async function streamChat(
  question: string,
  callbacks: StreamCallbacks,
  options?: {
    cnpj?: string;
    statementType?: string;
    conversationId?: string;
    signal?: AbortSignal;
    authHeaders?: Record<string, string>;
  }
): Promise<void> {
  try {
    const response = await fetch(`${API_URL}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(options?.authHeaders ?? {}),
      },
      body: JSON.stringify({
        question,
        cnpj: options?.cnpj,
        statement_type: options?.statementType,
        conversation_id: options?.conversationId,
      }),
      signal: options?.signal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`Falha na API (status ${response.status})`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = createNdjsonParser();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      dispatchEvents(parser.push(decoder.decode(value, { stream: true })), callbacks);
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    callbacks.onError(err instanceof Error ? err : new Error(String(err)));
  }
}

export async function fetchConversation(conversationId: string): Promise<
  { role: "user" | "assistant"; content: string; sources?: Source[] }[] | null
> {
  try {
    const { authHeaders } = await import("@/lib/auth");
    const response = await fetch(`${API_URL}/conversations/${conversationId}`, {
      headers: authHeaders(),
    });
    if (!response.ok) return null;
    const data = await response.json();
    return data.messages;
  } catch {
    return null;
  }
}

export async function registerUser(email: string, password: string): Promise<string> {
  const response = await fetch(`${API_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Erro ${response.status}`);
  }
  const data = await response.json();
  return data.access_token;
}

export async function loginUser(email: string, password: string): Promise<string> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "E-mail ou senha incorretos");
  }
  const data = await response.json();
  return data.access_token;
}

function dispatchEvents(events: StreamEvent[], callbacks: StreamCallbacks): void {
  for (const event of events) {
    if (event.type === "conversation") callbacks.onConversationId(event.conversation_id);
    else if (event.type === "sources") callbacks.onSources(event.sources);
    else if (event.type === "tool_call") callbacks.onToolCall(event.name, event.input);
    else if (event.type === "tool_result") callbacks.onToolResult(event.text);
    else if (event.type === "token") callbacks.onToken(event.text);
    else if (event.type === "error") callbacks.onError(new Error(event.message));
    else if (event.type === "done") callbacks.onDone();
  }
}
