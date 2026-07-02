"""
Índice de busca por palavra-chave (BM25), complementar à busca semântica
do Qdrant.

Por que isso existe: busca vetorial pura erra exatamente o tipo de coisa
que mais importa em finanças — tickers ("ITUB4"), códigos de conta exatos,
números específicos. "Parecido em significado" não é o que se quer nesses
casos; é "contém exatamente esse termo". BM25 resolve esse ponto cego.
"""
from __future__ import annotations

import pickle
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from rank_bm25 import BM25Okapi

from processing.chunking.cvm_chunker import StatementChunk


def _normalize_token(token: str) -> str:
    """Minúsculas + remove acentos, pra 'Patrimônio' e 'patrimonio' baterem igual."""
    normalized = unicodedata.normalize("NFKD", token.lower())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    raw_tokens = re.findall(r"[a-zA-Z0-9À-ÿ]+", text)
    return [_normalize_token(t) for t in raw_tokens]


@dataclass
class _StoredChunk:
    chunk_id: str
    text: str
    metadata: dict


class BM25Index:
    """Índice BM25 em memória, com persistência simples via pickle."""

    def __init__(self) -> None:
        self._bm25: Optional[BM25Okapi] = None
        self._chunks: list[_StoredChunk] = []

    def build(self, chunks: Iterable[StatementChunk]) -> None:
        self._chunks = [
            _StoredChunk(chunk_id=c.chunk_id, text=c.text, metadata=c.to_dict()) for c in chunks
        ]
        self._rebuild_bm25()

    def _rebuild_bm25(self) -> None:
        if not self._chunks:
            self._bm25 = None
            return
        tokenized_corpus = [tokenize(c.text) for c in self._chunks]
        self._bm25 = BM25Okapi(tokenized_corpus)

    def is_empty(self) -> bool:
        return self._bm25 is None or len(self._chunks) == 0

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float, dict]]:
        """
        Retorna até `limit` tuplas (chunk_id, score_bm25, metadata-com-texto),
        ordenadas por relevância (maior score primeiro).

        Importante: NÃO filtramos por "score > 0". A fórmula de IDF do BM25
        pode gerar scores negativos quando um termo aparece em praticamente
        todos os documentos do corpus (comum em corpus pequenos/uniformes,
        como em testes) — o que importa é a ordem relativa, não o sinal
        absoluto do score.
        """
        if self.is_empty():
            return []

        scores = self._bm25.get_scores(tokenize(query))
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:limit]
        return [
            (self._chunks[i].chunk_id, float(scores[i]), self._chunks[i].metadata)
            for i in ranked_indices
        ]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self._chunks, f)

    def load(self, path: Path) -> None:
        with path.open("rb") as f:
            self._chunks = pickle.load(f)
        self._rebuild_bm25()
