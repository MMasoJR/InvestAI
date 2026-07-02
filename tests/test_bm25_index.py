"""Testes unitários do BM25Index — busca por palavra-chave, sem nenhuma rede/modelo."""
from __future__ import annotations

from pathlib import Path

from embeddings.bm25_index import BM25Index, tokenize
from processing.chunking.cvm_chunker import StatementChunk


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


def test_tokenize_normalizes_case_and_accents() -> None:
    assert tokenize("Patrimônio Líquido") == ["patrimonio", "liquido"]


def test_search_on_empty_index_returns_empty_list() -> None:
    index = BM25Index()
    assert index.search("qualquer coisa") == []
    assert index.is_empty()


def test_search_finds_exact_keyword_match() -> None:
    index = BM25Index()
    index.build(
        [
            _make_chunk("c1", "Ativo total da empresa ITUB4 em 2023"),
            _make_chunk("c2", "Patrimônio líquido da empresa BBSE3 em 2023"),
            _make_chunk("c3", "Receita líquida de vendas no período"),
        ]
    )

    results = index.search("ITUB4")

    assert len(results) >= 1
    assert results[0][0] == "c1"  # melhor match deve ser o chunk que contém o ticker


def test_search_respects_limit() -> None:
    index = BM25Index()
    index.build([_make_chunk(f"c{i}", "ativo total da empresa") for i in range(5)])

    results = index.search("ativo total", limit=2)

    assert len(results) == 2


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    index = BM25Index()
    index.build([_make_chunk("c1", "Ativo total da empresa ITUB4")])

    path = tmp_path / "bm25.pkl"
    index.save(path)

    loaded = BM25Index()
    loaded.load(path)

    results = loaded.search("ITUB4")
    assert len(results) == 1
    assert results[0][0] == "c1"
