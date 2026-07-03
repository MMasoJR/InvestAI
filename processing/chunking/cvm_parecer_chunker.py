"""
Chunker dos arquivos de "parecer" da CVM — o Relatório do Auditor
Independente (DFP) / Relatório da Revisão Especial (ITR), publicados pela
CVM em `dfp_cia_aberta_parecer_AAAA.csv` / `itr_cia_aberta_parecer_AAAA.csv`. 

⚠️ AVISO IMPORTANTE SOBRE O SCHEMA:
No momento em que este módulo foi escrito, não havia acesso de rede
disponível pra confirmar o nome EXATO da coluna que contém o texto do
relatório (a CVM disponibiliza esse arquivo como ZIP, e a rede deste
ambiente de desenvolvimento bloqueia o domínio dados.cvm.gov.br). Por isso,
em vez de hard-codar um nome de coluna que poderia estar errado, este
módulo DETECTA AUTOMATICAMENTE a coluna de texto: escolhe, entre as
colunas de texto livre (string), a que tem o maior tamanho médio de
conteúdo — heurística sólida, já que o texto do relatório do auditor é,
de longe, o campo mais longo desse arquivo.

Quando você rodar isso na sua máquina (com internet livre), vale a pena
conferir uma vez se a detecção pegou a coluna certa — print(chunk.text[:200])
de um chunk e veja se parece o início de um relatório de auditoria. Se a
heurística errar, passe o nome da coluna manualmente via o parâmetro
`text_column` de `build_parecer_chunks`.

As colunas de identificação (CNPJ_CIA, DENOM_CIA, CD_CVM, DT_REFER,
ORDEM_EXERC) seguem o mesmo padrão confirmado nos arquivos de demonstração
(BPA/BPP/DRE/...) do mesmo conjunto de dados da CVM — essas, sim, têm alta
confiança de estarem corretas, por já estarem documentadas/validadas no
restante do projeto (ver cvm_chunker.py).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from processing.chunking.text_chunker import chunk_text

logger = logging.getLogger("processing.chunking.cvm_parecer_chunker")

# Colunas de identificação — mesma convenção usada nos arquivos de
# demonstração (ver REQUIRED_COLUMNS / GROUP_KEYS em cvm_chunker.py).
# Colunas confirmadas presentes nos arquivos de parecer reais da CVM.
# CD_CVM e ORDEM_EXERC NÃO existem nesses arquivos (schema real diferente
# das demonstrações financeiras BPA/BPP/DRE) — confirmado em execução real.
ID_COLUMNS = ["CNPJ_CIA", "DENOM_CIA", "DT_REFER"]

# Colunas que claramente NÃO são o texto do relatório, mesmo que sejam
# string — excluídas da heurística de detecção da coluna de texto.
KNOWN_NON_TEXT_COLUMNS = {
    "CNPJ_CIA", "DENOM_CIA", "CD_CVM", "GRUPO_DFP", "MOEDA", "ESCALA_MOEDA",
    "ORDEM_EXERC", "DT_REFER", "DT_FIM_EXERC", "DT_INI_EXERC", "VERSAO",
    "DT_RECEB", "LINK_DOC", "CD_CONTA", "DS_CONTA",
}

DEFAULT_MAX_CHARS = 1500
DEFAULT_OVERLAP_CHARS = 200


@dataclass(frozen=True)
class ParecerChunk:
    """Um pedaço do relatório do auditor independente, pronto para embedding."""

    text: str
    cnpj: str
    company_name: str
    cd_cvm: str
    reference_date: str
    period_end: str
    exercise_order: str
    source_doc_type: str
    chunk_index: int    # posição deste pedaço dentro do relatório completo
    total_chunks: int   # quantos pedaços o relatório completo gerou
    statement_type: str = "Relatório do Auditor Independente"
    chunk_id: str = field(default="")

    def dedup_key(self) -> tuple:
        return (self.cnpj, self.period_end, self.chunk_index)

    def to_dict(self) -> dict:
        return asdict(self)


def detect_text_column(df: pd.DataFrame) -> str:
    """
    Detecta a coluna que contém o texto do relatório, escolhendo — entre as
    colunas de tipo texto que não são identificação conhecida — a que tem o
    maior tamanho médio de conteúdo. Ver aviso no topo do arquivo.

    Usa `pd.api.types.is_string_dtype` (não comparação direta com `object`)
    pra funcionar tanto no pandas 2.x (onde strings são dtype `object`)
    quanto no pandas 3.x (onde existe um dtype `str` dedicado).
    """
    candidates = [
        col for col in df.columns
        if col not in KNOWN_NON_TEXT_COLUMNS and pd.api.types.is_string_dtype(df[col])
    ]
    if not candidates:
        raise ValueError(
            "Nenhuma coluna de texto candidata encontrada — o DataFrame não "
            "parece ser um arquivo de 'parecer' da CVM."
        )

    avg_lengths = {col: df[col].astype(str).str.len().mean() for col in candidates}
    best_column = max(avg_lengths, key=avg_lengths.get)
    logger.debug("Coluna de texto detectada: '%s' (tamanho médio: %.0f chars)", best_column, avg_lengths[best_column])
    return best_column


def build_parecer_chunks(
    df: pd.DataFrame,
    doc_type: str,
    text_column: Optional[str] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[ParecerChunk]:
    """
    Recebe um DataFrame lido de um Parquet de 'parecer' e retorna a lista de
    chunks (um relatório pode virar vários chunks, se for longo).

    Levanta ValueError se as colunas de identificação mínimas não existirem
    — isso permite que load_parecer_chunks pule, com segurança, arquivos
    que não sejam de fato um 'parecer' (mesmo padrão usado em cvm_chunker.py).
    """
    missing_id_columns = [c for c in ID_COLUMNS if c not in df.columns]
    if missing_id_columns:
        raise ValueError(
            f"DataFrame não tem o formato esperado de 'parecer' da CVM. "
            f"Colunas de identificação faltando: {missing_id_columns}"
        )

    resolved_text_column = text_column or detect_text_column(df)
    has_period_end = "DT_FIM_EXERC" in df.columns
    has_cd_cvm = "CD_CVM" in df.columns
    has_ordem_exerc = "ORDEM_EXERC" in df.columns

    chunks: list[ParecerChunk] = []
    for _, row in df.iterrows():
        raw_text = row.get(resolved_text_column)
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue

        period_end = str(row["DT_FIM_EXERC"]) if has_period_end else str(row["DT_REFER"])
        cd_cvm = str(row["CD_CVM"]) if has_cd_cvm else "0"
        ordem_exerc = str(row["ORDEM_EXERC"]) if has_ordem_exerc else "ÚNICO"

        pieces = chunk_text(raw_text, max_chars=max_chars, overlap_chars=overlap_chars)
        total = len(pieces)

        for index, piece in enumerate(pieces):
            chunk_id = (
                f"{row['CNPJ_CIA']}_{cd_cvm}_{period_end}_"
                f"{ordem_exerc}_parecer_{index}"
            ).replace(" ", "_")

            chunks.append(
                ParecerChunk(
                    text=piece,
                    cnpj=str(row["CNPJ_CIA"]),
                    company_name=str(row["DENOM_CIA"]),
                    cd_cvm=cd_cvm,
                    reference_date=str(row["DT_REFER"]),
                    period_end=period_end,
                    exercise_order=ordem_exerc,
                    source_doc_type=doc_type,
                    chunk_index=index,
                    total_chunks=total,
                    chunk_id=chunk_id,
                )
            )

    logger.info("Gerados %d chunks de parecer a partir de %d linhas", len(chunks), len(df))
    return chunks


def deduplicate_parecer_chunks(chunks: Iterable[ParecerChunk]) -> list[ParecerChunk]:
    """Mesma lógica de dedup usada em cvm_chunker.py — evita repetição entre anos."""
    seen: set[tuple] = set()
    result: list[ParecerChunk] = []
    for chunk in chunks:
        key = chunk.dedup_key()
        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    return result


def load_parecer_parquet_dir_chunks(processed_dir: Path, doc_type: str) -> list[ParecerChunk]:
    """
    Varre os Parquets processados em busca especificamente dos arquivos de
    'parecer' (identificados pelo nome do arquivo, ex.:
    dfp_cia_aberta_parecer_2023.parquet) e retorna a lista completa de
    chunks já deduplicados.
    """
    all_chunks: list[ParecerChunk] = []
    parecer_files = sorted(processed_dir.rglob("*parecer*.parquet"))

    if not parecer_files:
        logger.info("Nenhum arquivo de 'parecer' encontrado em %s", processed_dir)
        return []

    for parquet_path in parecer_files:
        df = pd.read_parquet(parquet_path)
        try:
            chunks = build_parecer_chunks(df, doc_type)
        except ValueError as exc:
            logger.warning("Pulando %s: %s", parquet_path.name, exc)
            continue
        all_chunks.extend(chunks)

    deduped = deduplicate_parecer_chunks(all_chunks)
    logger.info(
        "Total de parecer: %d chunks gerados, %d após deduplicação entre anos",
        len(all_chunks), len(deduped),
    )
    return deduped


def export_parecer_chunks_to_jsonl(chunks: Iterable[ParecerChunk], output_path: Path) -> int:
    """Exporta os chunks de parecer para JSONL — mesmo formato usado pelos chunks de demonstração."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
            count += 1
    logger.info("Exportados %d chunks de parecer para %s", count, output_path)
    return count
