"""
Serviço principal do assessor de investimentos: junta retrieval + geração
num único fluxo, com suporte opcional a tool-calling (cotações em tempo real).

Fluxo sem ferramentas (modo anterior, ainda funciona):
  pergunta → retrieval → geração → resposta

Fluxo com ferramentas (quando ToolExecutor é injetado):
  pergunta → retrieval → LLM c/ tools → (se tool_use:) executa ferramenta
           → LLM c/ resultado → resposta final

O loop de tool-calling é intencionalmente de profundidade 1 (uma rodada de
ferramenta por pergunta) — suficiente para o caso de uso de cotação e evita
loops infinitos. Se no futuro houver necessidade de múltiplas ferramentas em
sequência, aumentar o limite do loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

from backend.app.services.llm import LLMClient
from backend.app.services.retrieval import RetrievalService
from backend.app.tools.definitions import ALL_TOOLS

SYSTEM_PROMPT = """Você é um assessor de investimentos que responde com base nos documentos \
fornecidos no contexto abaixo, extraídos de demonstrações financeiras oficiais da CVM.

Regras obrigatórias:
- Nunca afirme previsões de preço ou de mercado com certeza absoluta.
- Sempre cite a fonte (empresa, demonstração e período) de cada informação relevante que usar.
- Se a informação não estiver no contexto fornecido, diga claramente que não tem dados \
suficientes em vez de inventar.
- Destaque riscos relevantes quando aplicável.
- Diferencie claramente fato (dado presente no documento) de interpretação (sua análise sobre \
esse dado).
- Use o histórico da conversa para entender referências (ex.: "essa empresa", "o ano anterior"), \
mas sempre busque a informação factual no contexto recuperado, nunca na sua memória.
- Quando usar a ferramenta de cotação, deixe claro que os dados de mercado são em tempo real \
e podem variar, e que cotação de mercado é diferente do valor patrimonial nas demonstrações."""


@dataclass(frozen=True)
class AssessorAnswer:
    answer: str
    sources: list[dict]


class AssessorService:
    def __init__(
        self,
        retrieval: RetrievalService,
        llm: LLMClient,
        tool_executor=None,   # Optional[ToolExecutor] — None desliga o tool-calling
    ) -> None:
        self.retrieval = retrieval
        self.llm = llm
        self.tool_executor = tool_executor

    def _build_sources_and_messages(
        self,
        question: str,
        cnpj: Optional[str],
        statement_type: Optional[str],
        history: Optional[list[dict]],
    ) -> tuple[list[dict], list[dict]]:
        context = self.retrieval.retrieve(question, cnpj=cnpj, statement_type=statement_type)
        sources = [
            {
                "company_name": r.metadata.get("company_name"),
                "statement_type": r.metadata.get("statement_type"),
                "period_end": r.metadata.get("period_end"),
                "score": r.score,
            }
            for r in context.results
        ]
        current_message = (
            f"Pergunta do usuário: {question}\n\n"
            f"Contexto recuperado da base de conhecimento:\n{context.to_prompt_context()}"
        )
        messages = list(history or []) + [{"role": "user", "content": current_message}]
        return sources, messages

    def ask(
        self,
        question: str,
        cnpj: Optional[str] = None,
        statement_type: Optional[str] = None,
        history: Optional[list[dict]] = None,
    ) -> AssessorAnswer:
        sources, messages = self._build_sources_and_messages(question, cnpj, statement_type, history)

        if self.tool_executor is None:
            answer_text = self.llm.generate(system_prompt=SYSTEM_PROMPT, messages=messages)
            return AssessorAnswer(answer=answer_text, sources=sources)

        # Primeiro turno: detecta se o LLM quer chamar alguma ferramenta.
        llm_response = self.llm.generate_with_tools(
            system_prompt=SYSTEM_PROMPT, messages=messages, tools=ALL_TOOLS
        )

        if llm_response.has_tool_uses:
            continuation = self.tool_executor.build_tool_result_messages(
                llm_response.tool_uses, llm_response.raw_content
            )
            final_messages = messages + continuation
            answer_text = self.llm.generate(system_prompt=SYSTEM_PROMPT, messages=final_messages)
        else:
            answer_text = llm_response.text

        return AssessorAnswer(answer=answer_text, sources=sources)

    def ask_stream(
        self,
        question: str,
        cnpj: Optional[str] = None,
        statement_type: Optional[str] = None,
        history: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        """
        Versão em streaming: fontes primeiro, depois tokens, depois done.
        Com tool-calling: detecta a ferramenta (chamada síncrona rápida),
        emite eventos de tool_call e tool_result, e depois faz streaming
        da resposta final. Sem ferramenta: streaming direto.
        """
        sources, messages = self._build_sources_and_messages(question, cnpj, statement_type, history)
        yield {"type": "sources", "sources": sources}

        if self.tool_executor is None:
            yield from self._stream_direct(messages)
            return

        # Detecta ferramenta (não-streaming, rápido — o modelo decide logo)
        llm_response = self.llm.generate_with_tools(
            system_prompt=SYSTEM_PROMPT, messages=messages, tools=ALL_TOOLS
        )

        if llm_response.has_tool_uses:
            for tool_use in llm_response.tool_uses:
                yield {"type": "tool_call", "name": tool_use["name"], "input": tool_use["input"]}

            continuation = self.tool_executor.build_tool_result_messages(
                llm_response.tool_uses, llm_response.raw_content
            )
            # Emite o resultado da ferramenta pro frontend (opcional mas útil)
            tool_result_text = continuation[-1]["content"][0]["content"] if continuation else ""
            yield {"type": "tool_result", "text": tool_result_text}

            final_messages = messages + continuation
            yield from self._stream_direct(final_messages)
        else:
            # LLM respondeu direto, sem ferramentas — emite o texto já gerado
            # como tokens individuais (sem chamar a API de novo)
            if llm_response.text:
                for word in llm_response.text.split(" "):
                    yield {"type": "token", "text": word + " "}
            yield {"type": "done"}

    def _stream_direct(self, messages: list[dict]) -> Iterator[dict]:
        for chunk in self.llm.generate_stream(system_prompt=SYSTEM_PROMPT, messages=messages):
            yield {"type": "token", "text": chunk}
        yield {"type": "done"}
