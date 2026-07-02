"""
Executor de ferramentas: recebe os `tool_use` blocks devolvidos pelo LLM e
despacha cada um para a função real correspondente, formatando o resultado
como texto que o LLM possa entender e citar.

Design deliberado: o executor não lança exceções — sempre retorna uma string
(mesmo que seja uma mensagem de erro/indisponibilidade). Isso garante que um
problema numa ferramenta não derruba a resposta do assessor inteiro: o LLM
recebe a mensagem de erro como resultado e pode comunicá-la ao usuário.
"""
from __future__ import annotations

import json
import logging

from backend.app.tools.market_data import BrapiClient, BrapiQuoteError

logger = logging.getLogger("backend.tools.executor")


class ToolExecutor:
    def __init__(self, brapi_client: BrapiClient) -> None:
        self._brapi = brapi_client

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """
        Executa uma ferramenta pelo nome e retorna o resultado como texto.
        Nunca levanta exceção — erros são comunicados como texto pra o LLM.
        """
        try:
            if tool_name == "get_market_quote":
                return self._get_market_quote(tool_input.get("tickers", []))
            return f"Ferramenta desconhecida: '{tool_name}'."
        except Exception as exc:
            logger.warning("Falha ao executar ferramenta '%s': %s", tool_name, exc)
            return f"Não foi possível executar '{tool_name}': {exc}"

    def _get_market_quote(self, tickers: list[str]) -> str:
        if not tickers:
            return "Nenhum ticker foi especificado."
        try:
            results = self._brapi.get_quotes(tickers)
        except BrapiQuoteError as exc:
            return str(exc)

        if not results:
            return f"Nenhum dado encontrado para: {', '.join(tickers)}."

        lines = [f"Cotações em tempo real (fonte: brapi.dev / B3):"]
        for r in results:
            ticker = r.get("symbol", "?")
            name = r.get("shortName", "")
            price = r.get("regularMarketPrice")
            change = r.get("regularMarketChange")
            change_pct = r.get("regularMarketChangePercent")
            high = r.get("regularMarketDayHigh")
            low = r.get("regularMarketDayLow")
            week52_high = r.get("fiftyTwoWeekHigh")
            week52_low = r.get("fiftyTwoWeekLow")

            parts = [f"\n{ticker} ({name}):"]
            if price is not None:
                parts.append(f"  Preço atual: R$ {price:,.2f}")
            if change is not None and change_pct is not None:
                sinal = "+" if change >= 0 else ""
                parts.append(f"  Variação no dia: {sinal}R$ {change:.2f} ({sinal}{change_pct:.2f}%)")
            if high is not None and low is not None:
                parts.append(f"  Máxima/Mínima do dia: R$ {high:,.2f} / R$ {low:,.2f}")
            if week52_high is not None and week52_low is not None:
                parts.append(f"  Máxima/Mínima 52 semanas: R$ {week52_high:,.2f} / R$ {week52_low:,.2f}")
            lines.extend(parts)

        return "\n".join(lines)

    def build_tool_result_messages(
        self, tool_uses: list[dict], assistant_content: list
    ) -> list[dict]:
        """
        Constrói a pair de mensagens (assistant com tool_use + user com
        tool_result) que a API da Anthropic exige pra continuar a conversa
        após uma chamada de ferramenta. Ver:
        https://docs.anthropic.com/en/docs/tool-use
        """
        tool_result_content = [
            {
                "type": "tool_result",
                "tool_use_id": tool_use["id"],
                "content": self.execute(tool_use["name"], tool_use["input"]),
            }
            for tool_use in tool_uses
        ]
        return [
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": tool_result_content},
        ]
