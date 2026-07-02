"""
Cliente da API brapi.dev — fonte de cotações em tempo real da B3.

Documentação oficial: https://brapi.dev/docs

Endpoint usado:
    GET https://brapi.dev/api/quote/{tickers}?token={token}

Parâmetros:
    tickers — tickers separados por vírgula (ex: ITUB4,BBSE3)
    token   — opcional para os 4 tickers gratuitos (PETR4, VALE3, MGLU3,
              ITUB4); obrigatório pra qualquer outro. Token grátis em
              https://brapi.dev

Estrutura da resposta (campos usados aqui):
    results[].symbol                  — ticker (ex: "ITUB4")
    results[].shortName               — nome curto da empresa
    results[].regularMarketPrice      — preço atual
    results[].regularMarketChange     — variação em R$
    results[].regularMarketChangePercent  — variação em %
    results[].regularMarketVolume     — volume negociado no dia
    results[].regularMarketDayHigh    — máxima do dia
    results[].regularMarketDayLow     — mínima do dia
    results[].fiftyTwoWeekHigh        — máxima em 52 semanas
    results[].fiftyTwoWeekLow         — mínima em 52 semanas
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("backend.tools.market_data")

BRAPI_BASE_URL = "https://brapi.dev/api"
REQUEST_TIMEOUT = 10


class BrapiQuoteError(RuntimeError):
    """Erro ao buscar cotação na brapi.dev — não deve derrubar o assessor,
    apenas retornar uma mensagem de indisponibilidade."""


class BrapiClient:
    """
    Cliente para a API brapi.dev.

    O `http_client` pode ser injetado nos testes com um `httpx.Client`
    configurado com `httpx.MockTransport` — sem nenhuma chamada de rede real.
    Em produção, um novo cliente é criado internamente se não for passado.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._token = token
        self._http = http_client

    def _make_client(self) -> httpx.Client:
        return self._http or httpx.Client(timeout=REQUEST_TIMEOUT)

    def get_quotes(self, tickers: list[str]) -> list[dict]:
        """
        Busca a cotação atual dos tickers especificados.
        Retorna uma lista de dicts com os campos do resultado da API.
        Levanta BrapiQuoteError em caso de falha — o chamador decide
        o que fazer (ex.: informar indisponibilidade ao usuário).
        """
        if not tickers:
            return []

        tickers_str = ",".join(t.strip().upper() for t in tickers)
        url = f"{BRAPI_BASE_URL}/quote/{tickers_str}"
        params = {}
        if self._token:
            params["token"] = self._token

        try:
            client = self._make_client()
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                raise BrapiQuoteError(
                    f"brapi.dev não retornou dados para: {tickers_str}. "
                    "Verifique se os tickers são válidos ou se um token é necessário."
                )
            return results

        except httpx.HTTPError as exc:
            raise BrapiQuoteError(f"Erro HTTP ao buscar cotação: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise BrapiQuoteError(f"Resposta inesperada da brapi.dev: {exc}") from exc
