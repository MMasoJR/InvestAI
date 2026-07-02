"""
LLM falso para testes.

Suporta dois comportamentos:
  - Normal: texto de resposta com contagem de documentos/histórico.
  - Tool-calling: se a última mensagem do usuário contiver um ticker
    (padrão [A-Z]{4}[0-9]{1,2}), retorna um tool_use block solicitando
    a ferramenta get_market_quote — simula o LLM decidindo chamar a ferramenta.

Nenhuma dessas chamadas faz requisição de rede real.
"""
from __future__ import annotations

import re
from typing import Iterator

from backend.app.services.llm import LLMResponse

_TICKER_PATTERN = re.compile(r'\b[A-Z]{4}[0-9]{1,2}\b')


class FakeLLMClient:
    def _base_response(self, messages: list[dict]) -> str:
        last_content = messages[-1]["content"] if messages else ""
        n_docs = last_content.count("[Documento") if isinstance(last_content, str) else 0
        n_history = len(messages) - 1
        return (
            f"[resposta-fake] contexto recebido com {n_docs} documento(s) relevante(s), "
            f"{n_history} mensagem(ns) de histórico."
        )

    def generate(self, system_prompt: str, messages: list[dict]) -> str:
        return self._base_response(messages)

    def generate_stream(self, system_prompt: str, messages: list[dict]) -> Iterator[str]:
        texto = self.generate(system_prompt, messages)
        palavras = texto.split(" ")
        for i, palavra in enumerate(palavras):
            yield palavra + (" " if i < len(palavras) - 1 else "")

    def generate_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        last_content = messages[-1].get("content", "") if messages else ""
        text_to_search = last_content if isinstance(last_content, str) else ""
        tickers = _TICKER_PATTERN.findall(text_to_search)

        if tickers:
            # Simula o LLM decidindo chamar a ferramenta de cotação
            tool_use_block = {
                "type": "tool_use",
                "id": "fake_tool_use_id_001",
                "name": "get_market_quote",
                "input": {"tickers": tickers},
            }
            return LLMResponse(
                text="",
                tool_uses=[{"id": "fake_tool_use_id_001", "name": "get_market_quote", "input": {"tickers": tickers}}],
                raw_content=[tool_use_block],
                stop_reason="tool_use",
            )

        return LLMResponse(
            text=self._base_response(messages),
            tool_uses=[],
            raw_content=[],
            stop_reason="end_turn",
        )
