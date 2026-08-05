"""
Chunker dos arquivos de "parecer" da CVM — o Relatório do Auditor
Independente / Declaração dos Diretores, publicados em:
  dfp_cia_aberta_parecer_AAAA.csv / itr_cia_aberta_parecer_AAAA.csv

Schema real confirmado nos dados da CVM (todos os anos testados):
  CNPJ_CIA              — CNPJ da empresa
  DT_REFER              — data de referência
  VERSAO                — versão do documento
  DENOM_CIA             — nome da empresa
  TP_RELAT_AUD          — tipo do relatório de auditoria (pode ser NaN)
  TP_PARECER_DECL       — categoria do item (~51 chars, ex: "Declaração dos Diretores...")
  NUM_ITEM_PARECER_DECL — número do item (cada empresa tem 3-5 itens)
  TXT_PARECER_DECL      — o texto real (~2114 chars médios por item)

Lógica central:
  Cada empresa tem MÚLTIPLAS linhas (um item por linha). Este chunker
  AGRUPA todos os itens da mesma empresa+data, concatena os textos, e
  depois divide o texto completo em chunks menores se necessário.
  Isso garante que o contexto de cada empresa seja coeso, não fragmentado
  em pedaços sem relação entre si.
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

# Colunas de identificação obrigatórias (confirmadas no schema real da CVM).
ID_COLUMNS = ["CNPJ_CIA", "DENOM_CIA", "DT_REFER"]

# Coluna de texto principal — confirmada nos dados reais.
# A heurística de detecção automática é mantida como fallback, mas agora
# também tentamos este nome primeiro.
TEXT_COLUMN_PRIMARY = "TXT_PARECER_DECL"

# Colunas que NÃO são texto livre — excluídas da heurística.
KNOWN_NON_TEXT_COLUMNS = {
    "CNPJ_CIA", "DENOM_CIA", "CD_CVM", "GRUPO_DFP", "MOEDA", "ESCALA_MOEDA",
    "ORDEM_EXERC", "DT_REFER", "DT_FIM_EXERC", "DT_INI_EXERC", "VERSAO",
    "DT_RECEB", "LINK_DOC", "CD_CONTA", "DS_CONTA",
    # Colunas do parecer que são categorias/índices, não texto livre:
    "TP_RELAT_AUD", "TP_PARECER_DECL", "NUM_ITEM_PARECER_DECL",
}

DEFAULT_MAX_CHARS = 1500
DEFAULT_OVERLAP_CHARS = 200


@dataclass(frozen=True)
class ParecerChunk:
    """Um pedaço do relatório do auditor/declaração dos diretores, pronto para embedding."""

    text: str
    cnpj: str
    company_name: str
    cd_cvm: str
    reference_date: str
    period_end: str
    exercise_order: str
    source_doc_type: str
    chunk_index: int
    total_chunks: int
    statement_type: str = "Relatório do Auditor Independente"
    chunk_id: str = field(default="")

    def dedup_key(self) -> tuple:
        return (self.cnpj, self.period_end, self.chunk_index)

    def to_dict(self) -> dict:
        return asdict(self)


def detect_text_column(df: pd.DataFrame) -> str:
    """
    Detecta a coluna de texto do relatório. Tenta o nome canônico primeiro
    ('TXT_PARECER_DECL'); se não existir, cai para heurística (coluna string
    com maior tamanho médio, excluindo as colunas de identificação/categoria).
    """
    if TEXT_COLUMN_PRIMARY in df.columns:
        logger.debug("Usando coluna canônica '%s'", TEXT_COLUMN_PRIMARY)
        return TEXT_COLUMN_PRIMARY

    # Fallback heurístico — para anos com schema diferente
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
    logger.debug("Heurística detectou: '%s' (tamanho médio: %.0f chars)", best_column, avg_lengths[best_column])
    return best_column


def build_parecer_chunks(
    df: pd.DataFrame,
    doc_type: str,
    text_column: Optional[str] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[ParecerChunk]:
    """
    Recebe um DataFrame de 'parecer' e retorna chunks prontos para embedding.

    Agrupa os itens de cada empresa (mesmo CNPJ + data) antes de chunkar —
    assim cada empresa vira um texto coeso, não linhas soltas sem contexto.
    """
    missing_id_columns = [c for c in ID_COLUMNS if c not in df.columns]
    if missing_id_columns:
        raise ValueError(
            f"DataFrame não tem o formato esperado de 'parecer' da CVM. "
            f"Colunas de identificação faltando: {missing_id_columns}"
        )

    resolved_text_column = text_column or detect_text_column(df)

    # Colunas opcionais — nem todos os anos têm todas
    has_period_end = "DT_FIM_EXERC" in df.columns
    has_cd_cvm = "CD_CVM" in df.columns
    has_ordem_exerc = "ORDEM_EXERC" in df.columns

    # Agrupa por empresa + data de referência e concatena todos os itens
    group_keys = ["CNPJ_CIA", "DENOM_CIA", "DT_REFER"]
    if has_period_end:
        group_keys.append("DT_FIM_EXERC")

    chunks: list[ParecerChunk] = []

    for group_values, group_df in df.groupby(group_keys, dropna=False):
        if isinstance(group_values, str):
            group_values = (group_values,)

        cnpj = str(group_values[0])
        denom_cia = str(group_values[1])
        dt_refer = str(group_values[2])
        period_end = str(group_values[3]) if has_period_end else dt_refer

        cd_cvm = str(group_df["CD_CVM"].iloc[0]) if has_cd_cvm else "0"
        ordem_exerc = str(group_df["ORDEM_EXERC"].iloc[0]) if has_ordem_exerc else "ÚNICO"

        # Ordena pelo número do item antes de concatenar, se disponível
        if "NUM_ITEM_PARECER_DECL" in group_df.columns:
            group_df = group_df.sort_values("NUM_ITEM_PARECER_DECL")

        # Concatena o tipo + texto de cada item em sequência
        text_parts = []
        for _, row in group_df.iterrows():
            tipo = row.get("TP_PARECER_DECL", "")
            texto = row.get(resolved_text_column, "")
            if not isinstance(texto, str) or not texto.strip():
                continue
            if isinstance(tipo, str) and tipo.strip():
                text_parts.append(f"[{tipo.strip()}]\n{texto.strip()}")
            else:
                text_parts.append(texto.strip())

        full_text = "\n\n".join(text_parts)
        if not full_text.strip():
            continue

        pieces = chunk_text(full_text, max_chars=max_chars, overlap_chars=overlap_chars)
        total = len(pieces)

        for index, piece in enumerate(pieces):
            chunk_id = (
                f"{cnpj}_{cd_cvm}_{period_end}_{ordem_exerc}_parecer_{index}"
            ).replace(" ", "_")

            chunks.append(
                ParecerChunk(
                    text=piece,
                    cnpj=cnpj,
                    company_name=denom_cia,
                    cd_cvm=cd_cvm,
                    reference_date=dt_refer,
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
    """Remove duplicatas entre anos (o mesmo período aparece como 'PENÚLTIMO' no ano seguinte)."""
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
    Varre os Parquets processados buscando arquivos de 'parecer' e retorna
    a lista completa de chunks já deduplicados.
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
    """Exporta os chunks para JSONL — mesmo formato dos chunks de demonstração."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
            count += 1
    logger.info("Exportados %d chunks de parecer para %s", count, output_path)
    return count
