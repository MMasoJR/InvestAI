"""
Testes unitários do módulo de chunking de demonstrações financeiras da CVM.
Usa DataFrames sintéticos que reproduzem fielmente o schema real (confirmado
no dicionário de dados da CVM): CNPJ_CIA, DENOM_CIA, CD_CVM, GRUPO_DFP, MOEDA,
ESCALA_MOEDA, ORDEM_EXERC, DT_REFER, DT_FIM_EXERC, CD_CONTA, DS_CONTA, VL_CONTA.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from processing.chunking.cvm_chunker import (
    build_statement_chunks,
    deduplicate_chunks,
    export_chunks_to_jsonl,
    load_parquet_dir_chunks,
)


def _make_bpa_dataframe() -> pd.DataFrame:
    """Simula um BPA_con com uma empresa, um período, contas hierárquicas."""
    base = {
        "CNPJ_CIA": "60.872.504/0001-23",
        "DENOM_CIA": "EMPRESA TESTE S.A.",
        "CD_CVM": "19348",
        "GRUPO_DFP": "DF Consolidado - Balanço Patrimonial Ativo",
        "MOEDA": "REAL",
        "ESCALA_MOEDA": "MIL",
        "ORDEM_EXERC": "ÚLTIMO",
        "DT_REFER": "2023-12-31",
        "DT_FIM_EXERC": "2023-12-31",
    }
    rows = [
        {**base, "CD_CONTA": "1", "DS_CONTA": "Ativo Total", "VL_CONTA": "2500000,00"},
        {**base, "CD_CONTA": "1.01", "DS_CONTA": "Ativo Circulante", "VL_CONTA": "800000,00"},
        {**base, "CD_CONTA": "1.01.01", "DS_CONTA": "Caixa e Equivalentes", "VL_CONTA": "50000,50"},
        {**base, "CD_CONTA": "1.02", "DS_CONTA": "Ativo Não Circulante", "VL_CONTA": "1700000,00"},
    ]
    return pd.DataFrame(rows)


def test_build_statement_chunks_groups_correctly() -> None:
    df = _make_bpa_dataframe()
    chunks = build_statement_chunks(df, doc_type="dfp")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.company_name == "EMPRESA TESTE S.A."
    assert chunk.statement_type == "Balanço Patrimonial Ativo"
    assert chunk.consolidation == "Consolidado"
    assert chunk.exercise_order == "ÚLTIMO"
    assert chunk.source_doc_type == "dfp"


def test_render_text_preserves_hierarchy_and_formats_currency() -> None:
    df = _make_bpa_dataframe()
    chunk = build_statement_chunks(df, doc_type="dfp")[0]

    assert "Empresa: EMPRESA TESTE S.A." in chunk.text
    assert "1 Ativo Total: 2.500.000,00 mil" in chunk.text
    # conta de 2º nível deve vir indentada (mais recuada que a de 1º nível)
    assert "  1.01 Ativo Circulante" in chunk.text
    # conta de 3º nível deve estar mais indentada ainda
    assert "    1.01.01 Caixa e Equivalentes" in chunk.text


def test_build_statement_chunks_raises_on_wrong_schema() -> None:
    df = pd.DataFrame({"coluna_qualquer": [1, 2, 3]})
    with pytest.raises(ValueError):
        build_statement_chunks(df, doc_type="dfp")


def test_two_companies_two_periods_yield_separate_chunks() -> None:
    df1 = _make_bpa_dataframe()
    df2 = _make_bpa_dataframe()
    df2["CNPJ_CIA"] = "11.111.111/0001-11"
    df2["DENOM_CIA"] = "OUTRA EMPRESA S.A."
    df = pd.concat([df1, df2], ignore_index=True)

    chunks = build_statement_chunks(df, doc_type="dfp")
    assert len(chunks) == 2
    nomes = {c.company_name for c in chunks}
    assert nomes == {"EMPRESA TESTE S.A.", "OUTRA EMPRESA S.A."}


def test_deduplicate_chunks_removes_repeated_period() -> None:
    df = _make_bpa_dataframe()
    chunk_a = build_statement_chunks(df, doc_type="dfp")[0]

    # Simula o mesmo período repetido como "PENÚLTIMO" no arquivo do ano seguinte
    df_penultimo = df.copy()
    df_penultimo["ORDEM_EXERC"] = "PENÚLTIMO"
    chunk_b = build_statement_chunks(df_penultimo, doc_type="dfp")[0]

    deduped = deduplicate_chunks([chunk_a, chunk_b])
    assert len(deduped) == 1
    assert deduped[0].chunk_id == chunk_a.chunk_id


def test_export_chunks_to_jsonl(tmp_path: Path) -> None:
    df = _make_bpa_dataframe()
    chunks = build_statement_chunks(df, doc_type="dfp")
    output_path = tmp_path / "chunks.jsonl"

    count = export_chunks_to_jsonl(chunks, output_path)

    assert count == 1
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1
    assert "EMPRESA TESTE S.A." in content[0]


def test_load_parquet_dir_chunks_skips_non_statement_files(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed" / "dfp" / "2023"
    processed_dir.mkdir(parents=True)

    # Arquivo válido (formato de demonstração)
    df_valid = _make_bpa_dataframe()
    df_valid.to_parquet(processed_dir / "dfp_cia_aberta_BPA_con_2023.parquet", index=False)

    # Arquivo fora do padrão (simula um 'parecer' de texto livre)
    df_invalid = pd.DataFrame({"texto_parecer": ["opinião do auditor aqui"]})
    df_invalid.to_parquet(processed_dir / "dfp_cia_aberta_parecer_2023.parquet", index=False)

    chunks = load_parquet_dir_chunks(processed_dir, doc_type="dfp")

    assert len(chunks) == 1
    assert chunks[0].company_name == "EMPRESA TESTE S.A."
