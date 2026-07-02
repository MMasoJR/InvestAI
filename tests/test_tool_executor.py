"""Testes do ToolExecutor — sem chamada de rede real."""
from __future__ import annotations

import httpx
import pytest

from backend.app.tools.executor import ToolExecutor
from backend.app.tools.market_data import BrapiClient

_FAKE_RESPONSE = {
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
        }
    ]
}


def _make_executor(response_data: dict, status_code: int = 200) -> ToolExecutor:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response_data)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    brapi = BrapiClient(http_client=http_client)
    return ToolExecutor(brapi_client=brapi)


def test_execute_get_market_quote_returns_formatted_text() -> None:
    executor = _make_executor(_FAKE_RESPONSE)
    result = executor.execute("get_market_quote", {"tickers": ["ITUB4"]})

    assert "ITUB4" in result
    assert "38.50" in result or "38,50" in result
    assert "brapi.dev" in result


def test_execute_get_market_quote_shows_variation() -> None:
    executor = _make_executor(_FAKE_RESPONSE)
    result = executor.execute("get_market_quote", {"tickers": ["ITUB4"]})

    assert "0.30" in result or "0,30" in result
    assert "0.79" in result or "0,79" in result


def test_execute_unknown_tool_returns_error_string_not_exception() -> None:
    executor = _make_executor(_FAKE_RESPONSE)
    result = executor.execute("ferramenta_inexistente", {})

    assert "desconhecida" in result.lower()


def test_execute_get_market_quote_api_error_returns_error_string() -> None:
    executor = _make_executor({}, status_code=500)
    result = executor.execute("get_market_quote", {"tickers": ["ITUB4"]})

    # Não deve levantar exceção — deve retornar mensagem de erro.
    assert isinstance(result, str)
    assert len(result) > 0


def test_execute_empty_tickers_returns_informative_string() -> None:
    executor = _make_executor(_FAKE_RESPONSE)
    result = executor.execute("get_market_quote", {"tickers": []})

    assert "especificado" in result.lower()


def test_build_tool_result_messages_structure() -> None:
    executor = _make_executor(_FAKE_RESPONSE)
    tool_uses = [{"id": "tu_001", "name": "get_market_quote", "input": {"tickers": ["ITUB4"]}}]
    fake_assistant_content = [{"type": "tool_use", "id": "tu_001", "name": "get_market_quote", "input": {"tickers": ["ITUB4"]}}]

    messages = executor.build_tool_result_messages(tool_uses, fake_assistant_content)

    assert len(messages) == 2
    assert messages[0]["role"] == "assistant"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "tool_result"
    assert messages[1]["content"][0]["tool_use_id"] == "tu_001"
    assert "ITUB4" in messages[1]["content"][0]["content"]
