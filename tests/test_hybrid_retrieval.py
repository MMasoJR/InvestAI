"""
Testes da busca híbrida (RetrievalService combinando Qdrant + BM25 via RRF).

Confirma que o fallback pra busca só-vetorial funciona quando nenhum
BM25Index é passado, e que a fusão realmente traz pra cima um resultado
que bate por palavra-chave exata (ticker), respeitando os filtros.
"""
from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient

from backend.app.services.retrieval import RetrievalService, reciprocal_rank_fusion
from embeddings.bm25_index import BM25Index
from embeddings.qdrant_index import QdrantIndexer
from processing.chunking.cvm_chunker import StatementChunk
from tests.fake_embedder import FakeEmbedder


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


def test_reciprocal_rank_fusion_promotes_item_ranked_first_in_both_lists() -> None:
    ranking_a = ["a", "b", "c"]
    ranking_b = ["a", "c", "b"]

    fused = reciprocal_rank_fusion([ranking_a, ranking_b])

    assert fused[0] == "a"


def test_retrieval_without_bm25_falls_back_to_vector_only(tmp_path: Path) -> None:
    client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    indexer.index_chunks([_make_chunk("c1", "Ativo total da empresa")])

    retrieval = RetrievalService(indexer=indexer, top_k=5, bm25_index=None)
    context = retrieval.retrieve("Ativo total da empresa")

    assert len(context.results) == 1


def test_hybrid_search_includes_exact_keyword_match(tmp_path: Path) -> None:
    chunks = [
        _make_chunk("c1", "Ativo total da empresa ITUB4 em 2023"),
        _make_chunk("c2", "Patrimônio líquido da empresa BBSE3 em 2023"),
        _make_chunk("c3", "Receita líquida de vendas no período"),
    ]

    client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    indexer.index_chunks(chunks)

    bm25 = BM25Index()
    bm25.build(chunks)

    retrieval = RetrievalService(indexer=indexer, top_k=2, bm25_index=bm25, fetch_k=10)
    context = retrieval.retrieve("ITUB4")

    chunk_ids = [r.metadata["chunk_id"] for r in context.results]
    assert "c1" in chunk_ids


def test_hybrid_search_respects_statement_type_filter(tmp_path: Path) -> None:
    chunks = [
        _make_chunk("c1", "Ativo da empresa", statement_type="Balanço Patrimonial Ativo"),
        _make_chunk("c2", "Ativo da empresa", statement_type="Demonstração do Resultado"),
    ]
    client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    indexer.index_chunks(chunks)

    bm25 = BM25Index()
    bm25.build(chunks)

    retrieval = RetrievalService(indexer=indexer, top_k=5, bm25_index=bm25, fetch_k=10)
    context = retrieval.retrieve("Ativo da empresa", statement_type="Demonstração do Resultado")

    chunk_ids = [r.metadata["chunk_id"] for r in context.results]
    assert chunk_ids == ["c2"]


def test_hybrid_search_with_empty_bm25_index_falls_back_to_vector(tmp_path: Path) -> None:
    client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    indexer.index_chunks([_make_chunk("c1", "Ativo total da empresa")])

    empty_bm25 = BM25Index()  # nunca teve build() chamado
    retrieval = RetrievalService(indexer=indexer, top_k=5, bm25_index=empty_bm25)
    context = retrieval.retrieve("Ativo total da empresa")

    assert len(context.results) == 1
