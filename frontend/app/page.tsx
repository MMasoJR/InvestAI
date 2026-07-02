"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChatInput } from "@/components/ChatInput";
import { ChatMessage } from "@/components/ChatMessage";
import { EmptyState } from "@/components/EmptyState";
import { fetchConversation, streamChat } from "@/lib/api";
import { authHeaders, clearToken, loadToken } from "@/lib/auth";
import type { ChatMessage as ChatMessageType, Source } from "@/types/chat";

const STORAGE_KEY = "investai:conversation_id";

function newId(): string {
  return Math.random().toString(36).slice(2);
}

export default function Page() {
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const router = useRouter();

  useEffect(() => {
    const token = loadToken();
    if (!token) {
      router.push("/login");
      return;
    }
    setIsAuthenticated(true);

    const storedId = localStorage.getItem(STORAGE_KEY);
    if (!storedId) return;

    fetchConversation(storedId).then((history) => {
      if (!history || history.length === 0) return;
      setConversationId(storedId);
      setMessages(
        history.map((m) => ({
          id: newId(),
          role: m.role,
          text: m.content,
          sources: m.sources as Source[] | undefined,
        }))
      );
    });
  }, [router]);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  function handleNewConversation() {
    abortRef.current?.abort();
    setMessages([]);
    setConversationId(null);
    localStorage.removeItem(STORAGE_KEY);
  }

  async function handleSend(question: string) {
    const userMessage: ChatMessageType = { id: newId(), role: "user", text: question };
    const assistantId = newId();
    const assistantMessage: ChatMessageType = {
      id: assistantId, role: "assistant", text: "", isStreaming: true,
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    function updateAssistant(updater: (msg: ChatMessageType) => ChatMessageType) {
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? updater(m) : m)));
    }

    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    await streamChat(question, {
      onConversationId: (id: string) => {
        setConversationId(id);
        localStorage.setItem(STORAGE_KEY, id);
      },
      onSources: (sources: Source[]) => {
        updateAssistant((m) => ({ ...m, sources }));
      },
      onToolCall: (name: string, input: Record<string, unknown>) => {
        updateAssistant((m) => ({
          ...m,
          toolCalls: [...(m.toolCalls ?? []), { name, input }],
        }));
      },
      onToolResult: (text: string) => {
        updateAssistant((m) => ({ ...m, toolResult: text }));
      },
      onToken: (text: string) => {
        updateAssistant((m) => ({ ...m, text: m.text + text }));
      },
      onDone: () => {
        updateAssistant((m) => ({ ...m, isStreaming: false }));
        setIsStreaming(false);
      },
      onError: (error: Error) => {
        if (error.message.includes("401")) {
          clearToken();
          router.push("/login");
          return;
        }
        updateAssistant((m) => ({
          ...m,
          text: `Não consegui falar com a API agora (${error.message}). Confirme que o backend está rodando em ${apiUrl}.`,
          isStreaming: false,
        }));
        setIsStreaming(false);
      },
    }, {
      signal: controller.signal,
      conversationId: conversationId ?? undefined,
      authHeaders: authHeaders(),
    });
  }

  if (!isAuthenticated) return null;

  return (
    <main className="mx-auto flex h-screen max-w-3xl flex-col px-4 py-6">
      <div className="flex items-center justify-between pb-4">
        <span className="font-mono text-xs uppercase tracking-widest text-ink-muted">InvestAI</span>
        <div className="flex gap-4">
          {messages.length > 0 && (
            <button
              onClick={handleNewConversation}
              className="font-mono text-xs text-ink-muted underline-offset-4 hover:text-gold hover:underline"
            >
              Nova conversa
            </button>
          )}
          <button
            onClick={handleLogout}
            className="font-mono text-xs text-ink-faint underline-offset-4 hover:text-ink hover:underline"
          >
            Sair
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <EmptyState onExampleClick={handleSend} />
        ) : (
          <div className="flex flex-col gap-6 pb-4">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}
          </div>
        )}
      </div>

      <div className="pt-4">
        <ChatInput onSend={handleSend} disabled={isStreaming} />
        <p className="mt-2 text-center font-mono text-[11px] text-ink-faint">
          O assessor responde com base em demonstrações financeiras públicas da CVM — não é recomendação de investimento.
        </p>
      </div>
    </main>
  );
}
