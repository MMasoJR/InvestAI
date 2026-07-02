"""
Testes do reranking (RetrievalService com Reranker) — confirma que os
candidatos são de fato reordenados pelo reranker, e que a expansão do
conjunto de busca (fetch_k > top_k) permite que o reranker recupere o
melhor resultado mesmo quando a busca vetorial pura (com o FakeEmbedder,
que não tem semântica real) não o colocaria em primeiro.
"""
from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient

from backend.app.services.retrieval import RetrievalService
from embeddings.bm25_index import BM25Index
from embeddings.qdrant_index import QdrantIndexer
from processing.chunking.cvm_chunker import StatementChunk
from tests.fake_embedder import FakeEmbedder
from tests.fake_reranker import FakeReranker


def _make_chunk(chunk_id: str, text: str, **overrides) -> StatementChunk:
    base = dict(
        text=text,
        cnpj="60.872.504/0001-23",
        company_name="EMPRESA TESTE S.A.",
        cd_cvm="19348",
        statement_type="Balanço Patrimonial Ativo",
        consolidation="Consolidado",
        reference_date="2023-12-31",
        period_end="2023-12-31",
        exercise_order="ÚLTIMO",
        source_doc_type="dfp",
        chunk_id=chunk_id,
    )
    base.update(overrides)
    return StatementChunk(**base)


def _make_indexer(tmp_path: Path, chunks: list[StatementChunk]) -> QdrantIndexer:
    client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    indexer.index_chunks(chunks)
    return indexer


def test_reranker_promotes_best_keyword_match_to_top(tmp_path: Path) -> None:
    chunks = [
        _make_chunk("c1", "Receita de vendas no período"),
        _make_chunk("c2", "Ativo total da empresa em 2023"),
        _make_chunk("c3", "Passivo circulante da empresa"),
    ]
    indexer = _make_indexer(tmp_path, chunks)

    retrieval = RetrievalService(indexer=indexer, top_k=1, fetch_k=3, reranker=FakeReranker())
    context = retrieval.retrieve("ativo total")

    assert len(context.results) == 1
    assert context.results[0].metadata["chunk_id"] == "c2"


def test_reranker_reorders_results_by_score(tmp_path: Path) -> None:
    chunks = [
        _make_chunk("c1", "informação irrelevante"),
        _make_chunk("c2", "ativo total patrimonio liquido"),
    ]
    indexer = _make_indexer(tmp_path, chunks)

    retrieval = RetrievalService(indexer=indexer, top_k=2, fetch_k=2, reranker=FakeReranker())
    context = retrieval.retrieve("ativo total patrimonio liquido")

    assert context.results[0].metadata["chunk_id"] == "c2"
    assert context.results[0].score > context.results[1].score


def test_without_reranker_returns_top_k_results(tmp_path: Path) -> None:
    chunks = [
        _make_chunk("c1", "Receita de vendas no período"),
        _make_chunk("c2", "Ativo total da empresa em 2023"),
        _make_chunk("c3", "Passivo circulante da empresa"),
    ]
    indexer = _make_indexer(tmp_path, chunks)

    retrieval = RetrievalService(indexer=indexer, top_k=1, fetch_k=3, reranker=None)
    context = retrieval.retrieve("ativo total")

    # Sem reranker, comportamento idêntico ao retrieval só-vetorial original.
    assert len(context.results) == 1


def test_reranker_combined_with_bm25_hybrid_search(tmp_path: Path) -> None:
    chunks = [
        _make_chunk("c1", "Receita de vendas no período"),
        _make_chunk("c2", "Ativo total da empresa ITUB4 em 2023"),
        _make_chunk("c3", "Passivo circulante da empresa"),
    ]
    indexer = _make_indexer(tmp_path, chunks)
    bm25 = BM25Index()
    bm25.build(chunks)

    retrieval = RetrievalService(
        indexer=indexer, top_k=1, fetch_k=3, bm25_index=bm25, reranker=FakeReranker()
    )
    context = retrieval.retrieve("ITUB4 ativo total")

    assert context.results[0].metadata["chunk_id"] == "c2"
