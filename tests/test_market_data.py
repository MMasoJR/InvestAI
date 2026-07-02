"""Testes do BrapiClient — sem chamada de rede real (httpx.MockTransport)."""
from __future__ import annotations

import json

import httpx
import pytest

from backend.app.tools.market_data import BrapiClient, BrapiQuoteError

_FAKE_QUOTE_RESPONSE = {
    "results": [
        {
            "symbol": "ITUB4",
            "shortName": "ITAUUNIBANCO ON",
            "regularMarketPrice": 38.50,
            "regularMarketChange": 0.30,
            "regularMarketChangePercent": 0.79,
            "regularMarketDayHigh": 38.90,
            "regularMarketDayLow": 38.10,
            "fiftyTwoWeekHigh": 42.00,
            "fiftyTwoWeekLow": 30.00,
            "regularMarketVolume": 12345678,
        }
    ]
}


def _make_client(response_data: dict, status_code: int = 200) -> BrapiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response_data)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return BrapiClient(http_client=http_client)


def test_get_quotes_returns_parsed_results() -> None:
    client = _make_client(_FAKE_QUOTE_RESPONSE)
    results = client.get_quotes(["ITUB4"])

    assert len(results) == 1
    assert results[0]["symbol"] == "ITUB4"
    assert results[0]["regularMarketPrice"] == 38.50


def test_get_quotes_uses_token_in_params() -> None:
    captured_url = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_url.append(str(request.url))
        return httpx.Response(200, json=_FAKE_QUOTE_RESPONSE)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = BrapiClient(token="meu-token", http_client=http_client)
    client.get_quotes(["ITUB4"])

    assert "token=meu-token" in captured_url[0]


def test_get_quotes_raises_on_http_error() -> None:
    client = _make_client({}, status_code=401)
    with pytest.raises(BrapiQuoteError):
        client.get_quotes(["ITUB4"])


def test_get_quotes_raises_when_results_empty() -> None:
    client = _make_client({"results": []})
    with pytest.raises(BrapiQuoteError, match="Verifique se os tickers são válidos"):
        client.get_quotes(["TICKER_INVALIDO"])


def test_get_quotes_returns_empty_for_empty_tickers() -> None:
    client = _make_client(_FAKE_QUOTE_RESPONSE)
    assert client.get_quotes([]) == []
