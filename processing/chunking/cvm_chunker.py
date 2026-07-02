"""
Camada de chunking: transforma os Parquets de demonstrações financeiras da CVM
(formato "longo" — uma linha por conta contábil) em chunks de texto prontos
para embedding.

Decisão de design (a mais importante deste módulo):
    Um chunk = uma demonstração financeira COMPLETA de uma empresa, em um
    único período/exercício (ex.: "Balanço Patrimonial Ativo Consolidado da
    Itaúsa em 31/12/2023"). Nunca quebramos uma demonstração no meio — isso
    preservaria números sem o contexto das contas vizinhas, o que é
    exatamente o tipo de erro que destrói a qualidade de um RAG financeiro.

Cada CSV original (BPA, BPP, DRE, DFC, DVA, DMPL) é um arquivo "longo": uma
linha por conta contábil, repetida pra cada empresa/período/exercício. Esse
módulo agrupa essas linhas e renderiza cada grupo como um bloco de texto
hierárquico (respeitando a árvore de contas via CD_CONTA).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd

logger = logging.getLogger("processing.chunking.cvm")

# Colunas exigidas nos arquivos "longos" de demonstrações (BPA/BPP/DRE/DFC/DVA/DMPL).
# Arquivos fora desse padrão (ex.: "parecer", que é texto livre do auditor)
# são ignorados por este chunker — terão um chunker dedicado no futuro.
REQUIRED_COLUMNS = {
    "CNPJ_CIA", "DENOM_CIA", "CD_CVM", "GRUPO_DFP", "MOEDA", "ESCALA_MOEDA",
    "ORDEM_EXERC", "DT_FIM_EXERC", "DT_REFER", "CD_CONTA", "DS_CONTA", "VL_CONTA",
}

GROUP_KEYS = [
    "CNPJ_CIA", "DENOM_CIA", "CD_CVM", "GRUPO_DFP",
    "DT_REFER", "DT_FIM_EXERC", "ORDEM_EXERC",
]


@dataclass(frozen=True)
class StatementChunk:
    """Um chunk pronto para embedding: texto + metadados ricos para filtro/citação."""

    text: str
    cnpj: str
    company_name: str
    cd_cvm: str
    statement_type: str        # ex: "Balanço Patrimonial Ativo"
    consolidation: str         # "Consolidado" ou "Individual"
    reference_date: str        # DT_REFER
    period_end: str            # DT_FIM_EXERC
    exercise_order: str        # "ÚLTIMO" ou "PENÚLTIMO"
    source_doc_type: str       # "dfp" ou "itr"
    chunk_id: str = field(default="")

    def dedup_key(self) -> tuple:
        """
        Chave usada para remover duplicatas entre arquivos de anos diferentes:
        o exercício 'PENÚLTIMO' do ano N costuma repetir o 'ÚLTIMO' do ano N-1.
        """
        return (self.cnpj, self.cd_cvm, self.statement_type, self.consolidation, self.period_end)

    def to_dict(self) -> dict:
        return asdict(self)


def _split_grupo_dfp(grupo_dfp: str) -> tuple[str, str]:
    """'DF Consolidado - Balanço Patrimonial Ativo' -> ('Consolidado', 'Balanço Patrimonial Ativo')."""
    if "-" not in grupo_dfp:
        return "Não especificado", grupo_dfp.strip()
    consolidacao_raw, demonstracao = grupo_dfp.split("-", 1)
    consolidacao = "Consolidado" if "Consolidado" in consolidacao_raw else "Individual"
    return consolidacao, demonstracao.strip()


def _format_valor(valor: float, escala_moeda: str) -> str:
    """Formata um valor monetário no padrão PT-BR (1.234.567,89), com sufixo de escala."""
    sinal = "-" if valor < 0 else ""
    valor_abs = abs(valor)
    inteiro, decimal = f"{valor_abs:,.2f}".split(".")
    inteiro_ptbr = inteiro.replace(",", ".")
    valor_ptbr = f"{sinal}{inteiro_ptbr},{decimal}"

    escala = (escala_moeda or "").strip().upper()
    sufixo = " mil" if escala == "MIL" else ""
    return f"{valor_ptbr}{sufixo}"


def _render_statement_text(group_df: pd.DataFrame) -> str:
    """
    Renderiza uma demonstração completa (já agrupada por empresa+período+exercício)
    como texto hierárquico legível, ordenado pelo código da conta contábil.

    Assume que CD_CONTA usa segmentos com zero-padding (ex.: '1.01', '1.10'),
    convenção real da CVM — o que torna a ordenação lexicográfica de string
    equivalente à ordenação numérica da árvore de contas.
    """
    first = group_df.iloc[0]
    consolidacao, demonstracao = _split_grupo_dfp(str(first["GRUPO_DFP"]))
    moeda = first.get("MOEDA", "REAL")
    escala = str(first.get("ESCALA_MOEDA", "") or "")

    header = (
        f"Demonstração: {demonstracao} ({consolidacao})\n"
        f"Empresa: {first['DENOM_CIA']} (CNPJ {first['CNPJ_CIA']}, código CVM {first['CD_CVM']})\n"
        f"Data de referência: {first['DT_REFER']} | Fim do exercício: {first['DT_FIM_EXERC']} "
        f"| Exercício: {first['ORDEM_EXERC']}\n"
        f"Moeda: {moeda}" + (f" (valores em {escala.lower()})" if escala else "") + "\n\n"
    )

    linhas = []
    for _, row in group_df.sort_values("CD_CONTA").iterrows():
        try:
            valor = float(str(row["VL_CONTA"]).replace(",", "."))
        except (ValueError, TypeError):
            valor = 0.0
        profundidade = str(row["CD_CONTA"]).count(".")
        indentacao = "  " * profundidade
        linhas.append(
            f"{indentacao}{row['CD_CONTA']} {row['DS_CONTA']}: {_format_valor(valor, escala)}"
        )

    return header + "\n".join(linhas)


def build_statement_chunks(df: pd.DataFrame, doc_type: str) -> list[StatementChunk]:
    """
    Recebe um DataFrame já lido de um Parquet de demonstração (BPA/BPP/DRE/DFC/DVA/DMPL)
    e retorna uma lista de chunks, um por (empresa, demonstração, período, exercício).

    Levanta ValueError se o DataFrame não tiver as colunas esperadas — isso é
    intencional: permite que load_parquet_dir_chunks pule, com segurança,
    arquivos fora do padrão (como 'parecer', texto livre do auditor).
    """
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"DataFrame não tem o formato esperado de demonstração financeira da CVM. "
            f"Colunas faltando: {sorted(missing)}"
        )

    chunks: list[StatementChunk] = []
    for keys, group in df.groupby(GROUP_KEYS, dropna=False):
        cnpj, denom_cia, cd_cvm, grupo_dfp, dt_refer, dt_fim_exerc, ordem_exerc = keys
        consolidacao, demonstracao = _split_grupo_dfp(str(grupo_dfp))
        text = _render_statement_text(group)
        chunk_id = (
            f"{cnpj}_{cd_cvm}_{dt_fim_exerc}_{ordem_exerc}_{demonstracao}"
        ).replace(" ", "_")

        chunks.append(
            StatementChunk(
                text=text,
                cnpj=str(cnpj),
                company_name=str(denom_cia),
                cd_cvm=str(cd_cvm),
                statement_type=demonstracao,
                consolidation=consolidacao,
                reference_date=str(dt_refer),
                period_end=str(dt_fim_exerc),
                exercise_order=str(ordem_exerc),
                source_doc_type=doc_type,
                chunk_id=chunk_id,
            )
        )

    logger.info("Gerados %d chunks a partir de %d linhas", len(chunks), len(df))
    return chunks


def deduplicate_chunks(chunks: Iterable[StatementChunk]) -> list[StatementChunk]:
    """
    Remove duplicatas entre arquivos de anos diferentes (ver docstring de
    StatementChunk.dedup_key). Mantém a primeira ocorrência — processe os
    arquivos em ordem cronológica crescente para manter a versão mais antiga
    e estável de cada período.
    """
    seen: set[tuple] = set()
    result: list[StatementChunk] = []
    for chunk in chunks:
        key = chunk.dedup_key()
        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    return result


def load_parquet_dir_chunks(processed_dir: Path, doc_type: str) -> list[StatementChunk]:
    """
    Varre todos os Parquets processados de um tipo de documento (dfp/itr) e
    retorna a lista completa de chunks já deduplicados, prontos para embedding.

    Ignora automaticamente arquivos que não tenham o formato "longo" esperado
    (ex.: 'parecer', texto livre do auditor — terá chunker próprio no futuro).
    """
    all_chunks: list[StatementChunk] = []
    for parquet_path in sorted(processed_dir.rglob("*.parquet")):
        df = pd.read_parquet(parquet_path)
        try:
            chunks = build_statement_chunks(df, doc_type)
        except ValueError:
            logger.info(
                "Pulando %s (fora do formato de demonstração esperado)", parquet_path.name
            )
            continue
        all_chunks.extend(chunks)

    deduped = deduplicate_chunks(all_chunks)
    logger.info(
        "Total: %d chunks gerados, %d após deduplicação entre anos",
        len(all_chunks), len(deduped),
    )
    return deduped


def export_chunks_to_jsonl(chunks: Iterable[StatementChunk], output_path: Path) -> int:
    """
    Exporta os chunks para JSONL (um JSON por linha) — formato de entrada
    natural para a próxima etapa do pipeline (geração de embeddings).
    Retorna a quantidade de chunks escritos.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
            count += 1
    logger.info("Exportados %d chunks para %s", count, output_path)
    return count
