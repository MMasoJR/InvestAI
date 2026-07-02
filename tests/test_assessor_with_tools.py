"""
Testes do AssessorService com tool-calling.

Usa FakeLLMClient (que simula chamar get_market_quote quando detecta tickers)
e um ToolExecutor com BrapiClient mockado — sem rede, sem custo de API.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from backend.app.dependencies import get_assessor_service
from backend.app.main import app
from backend.app.services.assessor import AssessorService
from backend.app.services.retrieval import RetrievalService
from backend.app.tools.executor import ToolExecutor
from backend.app.tools.market_data import BrapiClient
from embeddings.qdrant_index import QdrantIndexer
from processing.chunking.cvm_chunker import StatementChunk
from tests.fake_embedder import FakeEmbedder
from tests.fake_llm import FakeLLMClient

_FAKE_QUOTE = {
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


def _make_tool_executor(response_data: dict = None, status_code: int = 200) -> ToolExecutor:
    data = response_data if response_data is not None else _FAKE_QUOTE

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=data)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return ToolExecutor(brapi_client=BrapiClient(http_client=http_client))


def _make_chunk(chunk_id: str, text: str) -> StatementChunk:
    return StatementChunk(
        text=text, cnpj="60.872.504/0001-23", company_name="ITAUUNIBANCO S.A.",
        cd_cvm="19348", statement_type="Balanço Patrimonial Ativo", consolidation="Consolidado",
        reference_date="2023-12-31", period_end="2023-12-31", exercise_order="ÚLTIMO",
        source_doc_type="dfp", chunk_id=chunk_id,
    )


def _build_assessor(tmp_path: Path, tool_executor=None) -> AssessorService:
    client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    indexer.index_chunks([_make_chunk("c1", "Ativo total ITAUUNIBANCO 2023")])
    retrieval = RetrievalService(indexer=indexer, top_k=3)
    return AssessorService(retrieval=retrieval, llm=FakeLLMClient(), tool_executor=tool_executor)


def test_ask_without_tool_executor_works_as_before(tmp_path: Path) -> None:
    assessor = _build_assessor(tmp_path, tool_executor=None)
    answer = assessor.ask("Ativo total ITAUUNIBANCO 2023")

    assert "resposta-fake" in answer.answer
    assert isinstance(answer.sources, list)


def test_ask_without_ticker_does_not_call_tool(tmp_path: Path) -> None:
    assessor = _build_assessor(tmp_path, tool_executor=_make_tool_executor())
    answer = assessor.ask("Qual o ativo total da empresa em 2023?")

    # Sem ticker no texto, FakeLLM não aciona tool_use
    assert "resposta-fake" in answer.answer


def test_ask_with_ticker_executes_tool_and_includes_result(tmp_path: Path) -> None:
    assessor = _build_assessor(tmp_path, tool_executor=_make_tool_executor())
    # FakeLLM detecta "ITUB4" como ticker e retorna tool_use
    answer = assessor.ask("Qual o preço atual de ITUB4?")

    # Após executar a ferramenta, o LLM gera a resposta final (que no caso
    # do FakeLLM vai incluir a contagem de mensagens com o resultado da ferramenta)
    assert "resposta-fake" in answer.answer


def test_ask_stream_without_ticker_emits_expected_events(tmp_path: Path) -> None:
    assessor = _build_assessor(tmp_path, tool_executor=_make_tool_executor())
    events = list(assessor.ask_stream("Qual o ativo total da empresa?"))

    types = [e["type"] for e in events]
    assert types[0] == "sources"
    assert "token" in types
    assert types[-1] == "done"
    assert "tool_call" not in types  # sem ticker, sem ferramenta


def test_ask_stream_with_ticker_emits_tool_events(tmp_path: Path) -> None:
    assessor = _build_assessor(tmp_path, tool_executor=_make_tool_executor())
    events = list(assessor.ask_stream("Qual o preço atual de ITUB4?"))

    types = [e["type"] for e in events]
    assert types[0] == "sources"
    assert "tool_call" in types
    assert "tool_result" in types
    assert "token" in types
    assert types[-1] == "done"

    tool_call_event = next(e for e in events if e["type"] == "tool_call")
    assert tool_call_event["name"] == "get_market_quote"
    assert "ITUB4" in tool_call_event["input"]["tickers"]

    tool_result_event = next(e for e in events if e["type"] == "tool_result")
    assert "ITUB4" in tool_result_event["text"]


def _parse_ndjson(raw: str) -> list[dict]:
    return [json.loads(line) for line in raw.strip().splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_chat_stream_endpoint_with_tool_calling(tmp_path: Path, override_get_db) -> None:
    assessor = _build_assessor(tmp_path, tool_executor=_make_tool_executor())
    app.dependency_overrides[get_assessor_service] = lambda: assessor
    client = TestClient(app)

    response = client.post("/chat/stream", json={"question": "Qual o preço atual de ITUB4?"})

    assert response.status_code == 200
    events = _parse_ndjson(response.text)

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "done" in types
