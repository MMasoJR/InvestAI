"""
Testes de integração da API /chat e /chat/stream.

Usa Qdrant local real (pré-populado via QdrantIndexer + FakeEmbedder), um
FakeLLMClient (sem chamada de rede à Anthropic) e um banco SQLite em
memória (via fixture `override_get_db`, de tests/conftest.py) — testa o
fluxo completo de retrieval + persistência + resposta HTTP, sem custo de
rede/tokens e sem precisar de um Postgres real rodando.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from backend.app.dependencies import get_assessor_service
from backend.app.main import app
from backend.app.services.assessor import AssessorService
from backend.app.services.retrieval import RetrievalService
from embeddings.qdrant_index import QdrantIndexer
from processing.chunking.cvm_chunker import StatementChunk
from tests.fake_embedder import FakeEmbedder
from tests.fake_llm import FakeLLMClient


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_assessor_service, None)


def _make_chunk(chunk_id: str, text: str, company_name: str = "EMPRESA TESTE S.A.") -> StatementChunk:
    return StatementChunk(
        text=text,
        cnpj="60.872.504/0001-23",
        company_name=company_name,
        cd_cvm="19348",
        statement_type="Balanço Patrimonial Ativo",
        consolidation="Consolidado",
        reference_date="2023-12-31",
        period_end="2023-12-31",
        exercise_order="ÚLTIMO",
        source_doc_type="dfp",
        chunk_id=chunk_id,
    )


def _build_test_client(tmp_path: Path) -> TestClient:
    qdrant_client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=qdrant_client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    indexer.index_chunks(
        [_make_chunk("chunk-1", "Ativo total da empresa em 2023: R$ 2.500.000 mil")]
    )

    retrieval = RetrievalService(indexer=indexer, top_k=3)
    assessor = AssessorService(retrieval=retrieval, llm=FakeLLMClient())

    app.dependency_overrides[get_assessor_service] = lambda: assessor
    return TestClient(app)


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_returns_answer_sources_and_conversation_id(tmp_path: Path, override_get_db) -> None:
    client = _build_test_client(tmp_path)

    response = client.post(
        "/chat", json={"question": "Ativo total da empresa em 2023: R$ 2.500.000 mil"}
    )

    assert response.status_code == 200
    body = response.json()
    assert "contexto recebido com 1 documento" in body["answer"]
    assert len(body["sources"]) == 1
    assert body["sources"][0]["company_name"] == "EMPRESA TESTE S.A."
    assert body["sources"][0]["score"] > 0.999
    assert body["conversation_id"]  # gerado automaticamente


def test_chat_rejects_empty_question(tmp_path: Path, override_get_db) -> None:
    client = _build_test_client(tmp_path)
    response = client.post("/chat", json={"question": ""})
    assert response.status_code == 422


def test_chat_filters_by_cnpj(tmp_path: Path, override_get_db) -> None:
    qdrant_client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=qdrant_client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    chunk_a = _make_chunk("a-1", "Ativo da empresa A")
    chunk_b = StatementChunk(**{**chunk_a.to_dict(), "chunk_id": "b-1", "cnpj": "99.999.999/0001-99", "company_name": "OUTRA EMPRESA"})
    indexer.index_chunks([chunk_a, chunk_b])

    retrieval = RetrievalService(indexer=indexer, top_k=5)
    assessor = AssessorService(retrieval=retrieval, llm=FakeLLMClient())
    app.dependency_overrides[get_assessor_service] = lambda: assessor
    client = TestClient(app)

    response = client.post(
        "/chat", json={"question": "Ativo da empresa", "cnpj": "99.999.999/0001-99"}
    )

    body = response.json()
    assert len(body["sources"]) == 1
    assert body["sources"][0]["company_name"] == "OUTRA EMPRESA"


def test_chat_second_message_carries_history(tmp_path: Path, override_get_db) -> None:
    """Uma segunda pergunta na mesma conversa deve chegar ao LLM com 2 mensagens
    de histórico (a pergunta e a resposta da primeira rodada)."""
    client = _build_test_client(tmp_path)

    first = client.post("/chat", json={"question": "Ativo total da empresa em 2023: R$ 2.500.000 mil"})
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/chat",
        json={
            "question": "Ativo total da empresa em 2023: R$ 2.500.000 mil",
            "conversation_id": conversation_id,
        },
    )

    assert second.status_code == 200
    assert "2 mensagem(ns) de histórico" in second.json()["answer"]
    # E ambas as perguntas continuam na MESMA conversa
    assert second.json()["conversation_id"] == conversation_id


def _parse_ndjson(raw_text: str) -> list[dict]:
    return [json.loads(line) for line in raw_text.strip().splitlines() if line.strip()]


def test_chat_stream_emits_conversation_sources_tokens_then_done(tmp_path: Path, override_get_db) -> None:
    client = _build_test_client(tmp_path)

    response = client.post(
        "/chat/stream", json={"question": "Ativo total da empresa em 2023: R$ 2.500.000 mil"}
    )

    assert response.status_code == 200
    events = _parse_ndjson(response.text)

    assert events[0]["type"] == "conversation"
    assert events[0]["conversation_id"]

    assert events[1]["type"] == "sources"
    assert len(events[1]["sources"]) == 1
    assert events[1]["sources"][0]["company_name"] == "EMPRESA TESTE S.A."

    token_events = events[2:-1]
    assert all(e["type"] == "token" for e in token_events)
    texto_completo = "".join(e["text"] for e in token_events)
    assert "contexto recebido com 1 documento" in texto_completo

    assert events[-1]["type"] == "done"


def test_chat_stream_persists_messages_and_supports_followup(tmp_path: Path, db_session, override_get_db) -> None:
    client = _build_test_client(tmp_path)

    first_response = client.post(
        "/chat/stream", json={"question": "Ativo total da empresa em 2023: R$ 2.500.000 mil"}
    )
    first_events = _parse_ndjson(first_response.text)
    conversation_id = first_events[0]["conversation_id"]

    second_response = client.post(
        "/chat/stream",
        json={
            "question": "Ativo total da empresa em 2023: R$ 2.500.000 mil",
            "conversation_id": conversation_id,
        },
    )
    second_events = _parse_ndjson(second_response.text)
    texto_completo = "".join(e["text"] for e in second_events if e["type"] == "token")

    assert second_events[0]["conversation_id"] == conversation_id
    assert "2 mensagem(ns) de histórico" in texto_completo

    # Confirma via store que as 4 mensagens foram salvas no banco de testes
    from backend.app.services.conversation_store import ConversationStore
    store = ConversationStore(db_session)
    history = store.get_history(conversation_id)
    assert len(history) == 4  # 2 perguntas + 2 respostas
