"""
Testes do QdrantIndexer. Diferente dos testes de rede (que usam mocks),
estes testes rodam contra uma instância REAL do Qdrant em "modo local"
(QdrantClient(path=...)) — um backend embarcado, sem servidor, mantido
pela própria lib qdrant-client. Isso valida o comportamento de verdade
(criação de collection, upsert, busca, filtros) sem precisar de Docker
nem de rede.
"""
from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient

from embeddings.qdrant_index import QdrantIndexer
from processing.chunking.cvm_chunker import StatementChunk
from tests.fake_embedder import FakeEmbedder


def _make_chunk(chunk_id: str, text: str, cnpj: str = "60.872.504/0001-23", statement_type: str = "Balanço Patrimonial Ativo") -> StatementChunk:
    return StatementChunk(
        text=text,
        cnpj=cnpj,
        company_name="EMPRESA TESTE S.A.",
        cd_cvm="19348",
        statement_type=statement_type,
        consolidation="Consolidado",
        reference_date="2023-12-31",
        period_end="2023-12-31",
        exercise_order="ÚLTIMO",
        source_doc_type="dfp",
        chunk_id=chunk_id,
    )


def _make_indexer(tmp_path: Path) -> QdrantIndexer:
    client = QdrantClient(path=str(tmp_path / "qdrant_local"))
    indexer = QdrantIndexer(client=client, embedder=FakeEmbedder(dimension=16), collection_name="teste")
    indexer.ensure_collection()
    return indexer


def test_ensure_collection_is_idempotent(tmp_path: Path) -> None:
    indexer = _make_indexer(tmp_path)
    # Chamar de novo não deve levantar erro nem recriar a collection
    indexer.ensure_collection()
    assert indexer.client.collection_exists("teste")


def test_index_and_search_returns_exact_match_first(tmp_path: Path) -> None:
    indexer = _make_indexer(tmp_path)
    chunks = [
        _make_chunk("chunk-1", "Ativo total da empresa em 2023: R$ 2.500.000 mil"),
        _make_chunk("chunk-2", "Patrimônio líquido da empresa em 2023: R$ 900.000 mil"),
        _make_chunk("chunk-3", "Receita líquida de vendas no ano de 2023: R$ 1.200.000 mil"),
    ]

    total = indexer.index_chunks(chunks)
    assert total == 3

    # Buscar pelo texto EXATO de um chunk deve trazer esse mesmo chunk em
    # primeiro lugar, com score de similaridade máximo (vetores idênticos).
    results = indexer.search("Ativo total da empresa em 2023: R$ 2.500.000 mil", limit=3)
    assert len(results) == 3
    assert results[0].metadata["chunk_id"] == "chunk-1"
    assert results[0].score > 0.999


def test_reindexing_same_chunk_is_idempotent(tmp_path: Path) -> None:
    indexer = _make_indexer(tmp_path)
    chunk = _make_chunk("chunk-1", "texto original")

    indexer.index_chunks([chunk])
    indexer.index_chunks([chunk])  # reindexa o mesmo chunk de novo

    results = indexer.search("texto original", limit=10)
    # Não deve haver duplicata: mesmo chunk_id -> mesmo ID determinístico -> upsert
    assert len(results) == 1


def test_search_with_cnpj_filter(tmp_path: Path) -> None:
    indexer = _make_indexer(tmp_path)
    chunks = [
        _make_chunk("a-1", "Ativo total da empresa A", cnpj="11.111.111/0001-11"),
        _make_chunk("b-1", "Ativo total da empresa B", cnpj="22.222.222/0001-22"),
    ]
    indexer.index_chunks(chunks)

    results = indexer.search("Ativo total", limit=10, cnpj="11.111.111/0001-11")

    assert len(results) == 1
    assert results[0].metadata["cnpj"] == "11.111.111/0001-11"


def test_search_with_statement_type_filter(tmp_path: Path) -> None:
    indexer = _make_indexer(tmp_path)
    chunks = [
        _make_chunk("bp-1", "Balanço da empresa", statement_type="Balanço Patrimonial Ativo"),
        _make_chunk("dre-1", "Resultado da empresa", statement_type="Demonstração do Resultado"),
    ]
    indexer.index_chunks(chunks)

    results = indexer.search("empresa", limit=10, statement_type="Demonstração do Resultado")

    assert len(results) == 1
    assert results[0].metadata["statement_type"] == "Demonstração do Resultado"


def test_index_chunks_respects_batch_size(tmp_path: Path) -> None:
    indexer = _make_indexer(tmp_path)
    chunks = [_make_chunk(f"chunk-{i}", f"texto numero {i}") for i in range(10)]

    total = indexer.index_chunks(chunks, batch_size=3)

    assert total == 10
    results = indexer.search("texto numero 5", limit=10)
    assert len(results) == 10
