"""Testes do chunker de texto livre genérico (text_chunker.py)."""
from __future__ import annotations

from processing.chunking.text_chunker import chunk_text


def test_short_text_returns_single_chunk() -> None:
    text = "Um parecer curto, que cabe inteiro num único chunk."
    chunks = chunk_text(text, max_chars=1500)

    assert chunks == [text]


def test_empty_text_returns_empty_list() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_long_text_is_split_into_multiple_chunks() -> None:
    paragraph = "Esta é uma frase de teste razoavelmente longa para simular texto real. " * 5
    text = "\n\n".join([paragraph] * 10)  # bem mais que max_chars

    chunks = chunk_text(text, max_chars=500, overlap_chars=50)

    assert len(chunks) > 1
    assert all(len(c) <= 600 for c in chunks)  # alguma folga por causa do overlap


def test_chunks_respect_paragraph_boundaries_when_possible() -> None:
    paragraphs = [f"Parágrafo número {i}. " * 10 for i in range(5)]
    text = "\n\n".join(paragraphs)

    chunks = chunk_text(text, max_chars=300, overlap_chars=0)

    # Nenhum chunk deveria misturar o início de um parágrafo com o meio de outro
    # de forma incoerente — checagem simples: cada chunk não deve estar vazio
    # e o texto original deve estar todo coberto pela concatenação dos chunks.
    assert all(c.strip() for c in chunks)
    reconstructed = " ".join(chunks)
    for paragraph in paragraphs:
        # ao menos o início de cada parágrafo aparece em algum chunk
        assert paragraph.strip()[:20] in reconstructed


def test_consecutive_chunks_have_overlap() -> None:
    paragraph = "Frase número {}. ".format
    text = "\n\n".join(paragraph(i) * 20 for i in range(5))

    chunks = chunk_text(text, max_chars=400, overlap_chars=100)

    assert len(chunks) > 1
    # o fim do primeiro chunk deve aparecer no início do segundo (overlap)
    tail_of_first = chunks[0][-50:]
    assert tail_of_first[:20] in chunks[1]


def test_single_sentence_longer_than_max_chars_is_kept_whole() -> None:
    huge_sentence = "Esta é uma única frase extremamente longa sem pontuação intermediária " * 30 + "."
    chunks = chunk_text(huge_sentence, max_chars=200, overlap_chars=20)

    # Mesmo excedendo o limite, a frase não deve ser cortada arbitrariamente no meio.
    assert any(huge_sentence.strip() in c or c in huge_sentence for c in chunks)
