"""
Testes do chunker de 'parecer' (Relatório do Auditor Independente).

Usa DataFrames sintéticos com o schema assumido (ver aviso no topo de
cvm_parecer_chunker.py sobre a incerteza do nome exato da coluna de texto —
por isso a maior parte dos testes foca em garantir que a DETECÇÃO da coluna
funciona corretamente, não num nome de coluna específico).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from processing.chunking.cvm_parecer_chunker import (
    build_parecer_chunks,
    deduplicate_parecer_chunks,
    detect_text_column,
    export_parecer_chunks_to_jsonl,
    load_parecer_parquet_dir_chunks,
)

LONG_AUDIT_TEXT = (
    "Examinamos as demonstrações financeiras da Empresa Teste S.A., que compreendem o "
    "balanço patrimonial em 31 de dezembro de 2023 e as respectivas demonstrações do "
    "resultado, das mutações do patrimônio líquido e dos fluxos de caixa. Em nossa "
    "opinião, as demonstrações financeiras acima referidas apresentam adequadamente, "
    "em todos os aspectos relevantes, a posição patrimonial e financeira da Companhia."
)


def _make_parecer_dataframe(text_column_name: str = "TX_PARECER", text: str = LONG_AUDIT_TEXT) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "CNPJ_CIA": "60.872.504/0001-23",
                "DENOM_CIA": "EMPRESA TESTE S.A.",
                "CD_CVM": "19348",
                "DT_REFER": "2023-12-31",
                "DT_FIM_EXERC": "2023-12-31",
                "ORDEM_EXERC": "ÚLTIMO",
                "VERSAO": "1",
                text_column_name: text,
            }
        ]
    )


def test_detect_text_column_picks_longest_string_column() -> None:
    df = _make_parecer_dataframe(text_column_name="TX_PARECER")
    assert detect_text_column(df) == "TX_PARECER"


def test_detect_text_column_works_regardless_of_actual_column_name() -> None:
    # Simula a incerteza real: não sabemos o nome exato, mas a heurística
    # deve achar a coluna de texto longo de qualquer forma.
    df = _make_parecer_dataframe(text_column_name="ALGUM_NOME_DIFERENTE")
    assert detect_text_column(df) == "ALGUM_NOME_DIFERENTE"


def test_detect_text_column_raises_when_no_candidate() -> None:
    df = pd.DataFrame({"CNPJ_CIA": ["123"], "DT_REFER": ["2023-12-31"]})
    with pytest.raises(ValueError):
        detect_text_column(df)


def test_build_parecer_chunks_short_text_yields_single_chunk() -> None:
    df = _make_parecer_dataframe()
    chunks = build_parecer_chunks(df, doc_type="dfp")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.company_name == "EMPRESA TESTE S.A."
    assert chunk.statement_type == "Relatório do Auditor Independente"
    assert chunk.total_chunks == 1
    assert chunk.chunk_index == 0
    assert "Examinamos as demonstrações financeiras" in chunk.text


def test_build_parecer_chunks_long_text_yields_multiple_chunks() -> None:
    long_text = (LONG_AUDIT_TEXT + "\n\n") * 20  # bem além do max_chars padrão
    df = _make_parecer_dataframe(text="\n\n".join([LONG_AUDIT_TEXT] * 20))

    chunks = build_parecer_chunks(df, doc_type="dfp", max_chars=500, overlap_chars=50)

    assert len(chunks) > 1
    assert all(c.total_chunks == len(chunks) for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_build_parecer_chunks_raises_on_wrong_schema() -> None:
    df = pd.DataFrame({"coluna_qualquer": [1, 2, 3]})
    with pytest.raises(ValueError):
        build_parecer_chunks(df, doc_type="dfp")


def test_build_parecer_chunks_skips_empty_text_rows() -> None:
    df = _make_parecer_dataframe(text="")
    chunks = build_parecer_chunks(df, doc_type="dfp")
    assert chunks == []


def test_explicit_text_column_overrides_heuristic() -> None:
    df = _make_parecer_dataframe(text_column_name="COLUNA_CERTA")
    df["COLUNA_ENGANOSA"] = ["x" * 10000]  # mais longa, mas não é o texto certo

    chunks = build_parecer_chunks(df, doc_type="dfp", text_column="COLUNA_CERTA")

    assert len(chunks) == 1
    assert "Examinamos" in chunks[0].text


def test_deduplicate_parecer_chunks_removes_repeated_period() -> None:
    df = _make_parecer_dataframe()
    chunk_a = build_parecer_chunks(df, doc_type="dfp")[0]

    df_penultimo = df.copy()
    df_penultimo["ORDEM_EXERC"] = "PENÚLTIMO"
    chunk_b = build_parecer_chunks(df_penultimo, doc_type="dfp")[0]

    deduped = deduplicate_parecer_chunks([chunk_a, chunk_b])
    assert len(deduped) == 1


def test_export_parecer_chunks_to_jsonl(tmp_path: Path) -> None:
    df = _make_parecer_dataframe()
    chunks = build_parecer_chunks(df, doc_type="dfp")
    output_path = tmp_path / "parecer_chunks.jsonl"

    count = export_parecer_chunks_to_jsonl(chunks, output_path)

    assert count == 1
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "EMPRESA TESTE S.A." in content


def test_load_parecer_parquet_dir_chunks_finds_only_parecer_files(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed" / "dfp" / "2023"
    processed_dir.mkdir(parents=True)

    df_parecer = _make_parecer_dataframe()
    df_parecer.to_parquet(processed_dir / "dfp_cia_aberta_parecer_2023.parquet", index=False)

    # Arquivo de demonstração normal — não deve ser pego por este loader.
    df_other = pd.DataFrame({"coluna_qualquer": [1, 2, 3]})
    df_other.to_parquet(processed_dir / "dfp_cia_aberta_BPA_con_2023.parquet", index=False)

    chunks = load_parecer_parquet_dir_chunks(processed_dir, doc_type="dfp")

    assert len(chunks) == 1
    assert chunks[0].company_name == "EMPRESA TESTE S.A."


def test_load_parecer_parquet_dir_chunks_returns_empty_when_no_parecer_file(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed" / "dfp" / "2023"
    processed_dir.mkdir(parents=True)
    pd.DataFrame({"x": [1]}).to_parquet(processed_dir / "dfp_cia_aberta_BPA_con_2023.parquet", index=False)

    chunks = load_parecer_parquet_dir_chunks(processed_dir, doc_type="dfp")
    assert chunks == []
