"""
Reranker falso para testes: pontua cada documento pela quantidade de
termos da pergunta que aparecem nele (sobreposição de palavras-chave) —
determinístico, sem nenhum modelo real nem chamada de rede. Suficiente
pra provar que o RetrievalService está de fato chamando o reranker e
respeitando a ordem que ele devolve.
"""
from __future__ import annotations

from typing import Sequence


class FakeReranker:
    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        query_terms = set(query.lower().split())
        scores = []
        for doc in documents:
            doc_lower = doc.lower()
            score = sum(1.0 for term in query_terms if term in doc_lower)
            scores.append(score)
        return scores
