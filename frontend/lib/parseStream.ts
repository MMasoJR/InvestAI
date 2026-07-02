import type { StreamEvent } from "@/types/chat";

/**
 * Parser de streaming NDJSON (um objeto JSON por linha).
 *
 * Os pedaços que chegam de um ReadableStream do fetch não respeitam limites
 * de linha — uma linha pode chegar partida em dois pedaços, ou várias linhas
 * podem chegar juntas num único pedaço. Esse parser acumula um buffer e só
 * devolve eventos de linhas já completas (fechadas por "\n").
 */
export function createNdjsonParser() {
  let buffer = "";

  function push(chunk: string): StreamEvent[] {
    buffer += chunk;
    const lines = buffer.split("\n");
    // A última posição pode ser uma linha ainda incompleta — guarda para a próxima chamada.
    buffer = lines.pop() ?? "";

    const events: StreamEvent[] = [];
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        events.push(JSON.parse(trimmed) as StreamEvent);
      } catch {
        // Linha corrompida — ignora silenciosamente em vez de derrubar o chat.
      }
    }
    return events;
  }

  return { push };
}
