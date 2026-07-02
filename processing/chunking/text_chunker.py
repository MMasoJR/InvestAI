"""
Chunker de texto livre, genérico e reutilizável — diferente do chunker de
demonstrações financeiras (cvm_chunker.py), que monta UM chunk por
demonstração inteira, este módulo lida com texto corrido potencialmente
longo (como o Relatório do Auditor Independente), que pode ter várias
páginas e precisa ser dividido em pedaços menores pra gerar embeddings de
boa qualidade.

Estratégia: divide primeiro por parágrafo (linha em branco), e só quebra um
parágrafo no meio se ele sozinho já ultrapassar max_chars — nesse caso,
quebra por frase. Mantém uma sobreposição (overlap) entre chunks
consecutivos pra não perder contexto na fronteira entre um pedaço e outro.
"""
from __future__ import annotations

import re


def _split_into_paragraphs(text: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paragraphs if p.strip()]


def _split_into_sentences(text: str) -> list[str]:
    # Divisão simples por pontuação de fim de frase, suficiente para texto
    # em português formal (relatórios de auditoria) sem precisar de uma
    # lib de NLP completa.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def chunk_text(text: str, max_chars: int = 1500, overlap_chars: int = 200) -> list[str]:
    """
    Divide um texto longo em pedaços de até `max_chars` caracteres, com
    `overlap_chars` de sobreposição entre pedaços consecutivos.

    Se o texto inteiro já couber em max_chars, retorna ele como um único
    chunk (sem split nenhum) — isso é o caso comum pra relatórios mais
    curtos, e evita fragmentação desnecessária.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = _split_into_paragraphs(text)
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            units.append(paragraph)
        else:
            units.extend(_split_into_sentences(paragraph))

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit

        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            # A sobreposição pega o final do chunk anterior, pra dar
            # continuidade de contexto ao próximo.
            overlap_tail = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = f"{overlap_tail}\n\n{unit}".strip() if overlap_tail else unit
        else:
            # Uma única unidade (frase) já maior que max_chars sozinha —
            # caso raro, mas tratado: entra inteira mesmo excedendo o limite,
            # em vez de cortar uma frase no meio de forma arbitrária.
            chunks.append(unit)
            current = ""

    if current:
        chunks.append(current)

    return chunks
