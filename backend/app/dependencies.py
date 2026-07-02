"""
Construção e injeção de dependências da API.

Centralizado aqui por dois motivos:
1. O resto do código (routers) não precisa saber como cada peça é montada.
2. Nos testes, basta sobrescrever get_assessor_service via
   app.dependency_overrides para injetar versões falsas/locais, sem tocar
   em nenhum outro arquivo (ver tests/test_chat_api.py).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient

from backend.app.config import get_settings
from backend.app.services.assessor import AssessorService
from backend.app.services.llm import AnthropicLLMClient
from backend.app.services.retrieval import RetrievalService
from embeddings.bm25_index import BM25Index
from embeddings.embedder import BGEM3Embedder
from embeddings.qdrant_index import QdrantIndexer
from embeddings.reranker import CrossEncoderReranker, Reranker

logger = logging.getLogger("backend.dependencies")


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return QdrantClient(path=settings.qdrant_local_path)


@lru_cache
def get_indexer() -> QdrantIndexer:
    settings = get_settings()
    embedder = BGEM3Embedder()
    return QdrantIndexer(
        client=get_qdrant_client(), embedder=embedder, collection_name=settings.collection_name
    )


@lru_cache
def get_bm25_index() -> BM25Index | None:
    """
    Carrega o índice BM25 do disco, se ele já tiver sido gerado (ver
    `embeddings/cli.py`). Se o arquivo não existir ainda, retorna None —
    a RetrievalService cai automaticamente para busca só-vetorial nesse caso.
    """
    path = Path(get_settings().bm25_index_path)
    if not path.exists():
        logger.warning(
            "Índice BM25 não encontrado em %s — rodando só com busca semântica. "
            "Rode 'python -m embeddings.cli' para gerar o índice híbrido.",
            path,
        )
        return None

    index = BM25Index()
    index.load(path)
    logger.info("Índice BM25 carregado de %s.", path)
    return index


@lru_cache
def get_reranker() -> Reranker | None:
    """
    Instancia o cross-encoder de reranking, se habilitado em configuração.
    Pode ser desligado via INVESTAI_ENABLE_RERANKING=false (ex.: pra reduzir
    latência/memória numa máquina mais fraca) sem quebrar nada — o
    RetrievalService simplesmente não reordena os candidatos nesse caso.
    """
    if not get_settings().enable_reranking:
        return None
    return CrossEncoderReranker()


@lru_cache
def get_retrieval_service() -> RetrievalService:
    return RetrievalService(
        indexer=get_indexer(),
        top_k=get_settings().top_k,
        bm25_index=get_bm25_index(),
        reranker=get_reranker(),
    )


@lru_cache
def get_llm_client() -> AnthropicLLMClient:
    return AnthropicLLMClient(model=get_settings().llm_model)


@lru_cache
def get_tool_executor():
    """
    Instancia o ToolExecutor com o BrapiClient configurado.
    INVESTAI_BRAPI_TOKEN é opcional — sem ele, só PETR4/VALE3/MGLU3/ITUB4
    funcionam gratuitamente.
    """
    from backend.app.tools.executor import ToolExecutor
    from backend.app.tools.market_data import BrapiClient
    return ToolExecutor(brapi_client=BrapiClient(token=get_settings().brapi_token))


def get_assessor_service() -> AssessorService:
    """
    Dependency usada pelo router de chat. Em produção, monta o serviço real
    (Qdrant + BM25 + bge-m3 + Claude + brapi.dev). Em teste, é substituída por
    app.dependency_overrides[get_assessor_service] = lambda: <fake>.
    """
    return AssessorService(
        retrieval=get_retrieval_service(),
        llm=get_llm_client(),
        tool_executor=get_tool_executor(),
    )
