"""
Cliente de LLM usado para gerar as respostas do assessor.

Como em embeddings/embedder.py, definido como Protocol — assim é possível
trocar de provedor (Claude, GPT, etc.) sem alterar o resto do pipeline.

Recebe uma lista de mensagens (não só a pergunta atual) para suportar
conversas com múltiplos turnos. Suporta também tool-calling: a chamada
generate_with_tools() retorna um LLMResponse que inclui os tool_use blocks
gerados pelo modelo, se ele decidiu chamar alguma ferramenta.

Existem dois modos de geração:
  - generate(): resposta completa de uma vez (usado após tool execution).
  - generate_stream(): pedaços de texto conforme o modelo gera ("digitação").
  - generate_with_tools(): para primeiro turno, detecta se ferramentas foram
    chamadas antes de gerar a resposta final.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Protocol


@dataclass
class LLMResponse:
    """Resultado de uma chamada generate_with_tools."""

    text: str
    tool_uses: list[dict] = field(default_factory=list)
    # Os content blocks originais da API, necessários para construir a
    # mensagem de continuação após tool execution (passados como-está de volta
    # para a API — a lib serializa automaticamente).
    raw_content: list = field(default_factory=list)
    stop_reason: str = "end_turn"

    @property
    def has_tool_uses(self) -> bool:
        return len(self.tool_uses) > 0


class LLMClient(Protocol):
    def generate(self, system_prompt: str, messages: list[dict]) -> str:
        """Recebe o prompt de sistema + histórico de mensagens e retorna texto."""
        ...

    def generate_stream(self, system_prompt: str, messages: list[dict]) -> Iterator[str]:
        """Mesma coisa, mas devolvendo pedaços de texto conforme são gerados."""
        ...

    def generate_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        """
        Chamada com tool definitions — retorna um LLMResponse com texto E/OU
        tool_use blocks, dependendo do que o modelo decidiu fazer.
        Se stop_reason for 'tool_use', o LLM quer executar uma ferramenta;
        o chamador deve executar, adicionar tool_results nas mensagens e
        chamar generate() ou generate_stream() para a resposta final.
        """
        ...


class AnthropicLLMClient:
    """
    Cliente de produção: chama a API da Anthropic (Claude).

    Lê a chave de API da variável de ambiente ANTHROPIC_API_KEY (padrão do
    SDK oficial — não precisa passar a chave em código nenhum momento).
    O import do SDK é tardio para que o resto do pipeline não dependa dele.
    """

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 1024) -> None:
        from anthropic import Anthropic  # import tardio

        self._client = Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, system_prompt: str, messages: list[dict]) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return "".join(block.text for block in response.content if block.type == "text")

    def generate_stream(self, system_prompt: str, messages: list[dict]) -> Iterator[str]:
        with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=messages,
        ) as stream:
            yield from stream.text_stream

    def generate_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )
        text = ""
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_uses.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return LLMResponse(
            text=text,
            tool_uses=tool_uses,
            raw_content=response.content,
            stop_reason=response.stop_reason or "end_turn",
        )
