"""
Camada de retrieval: combina busca vetorial (Qdrant) com busca por palavra-
chave (BM25) via Reciprocal Rank Fusion (RRF), opcionalmente reordena os
candidatos com um reranker (cross-encoder), e formata o resultado final
como contexto citável para o prompt do LLM.

Tanto o BM25Index quanto o Reranker são opcionais — sem eles, o serviço
funciona em modo "só busca vetorial", mantendo compatibilidade com versões
anteriores do projeto.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from embeddings.bm25_index import BM25Index
from embeddings.qdrant_index import QdrantIndexer, SearchResult
from embeddings.reranker import Reranker


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    """
    Combina várias listas rankeadas (por ID) num ranking único, somando
    1/(k+posição) de cada lista. É o método padrão (RRF) pra fundir buscas
    de natureza diferente sem precisar normalizar as escalas de score entre
    elas — cosseno do Qdrant e score do BM25 não são comparáveis diretamente.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item_id: scores[item_id], reverse=True)


@dataclass(frozen=True)
class RetrievedContext:
    results: list[SearchResult]

    def is_empty(self) -> bool:
        return len(self.results) == 0

    def to_prompt_context(self) -> str:
        """Formata os chunks recuperados como blocos numerados e citáveis."""
        if self.is_empty():
            return "Nenhum documento relevante foi encontrado na base de conhecimento."

        blocks = []
        for i, result in enumerate(self.results, start=1):
            meta = result.metadata
            cabecalho = (
                f"[Documento {i}] Empresa: {meta.get('company_name', '?')} | "
                f"Demonstração: {meta.get('statement_type', '?')} | "
                f"Período: {meta.get('period_end', '?')} | "
                f"Relevância: {result.score:.2f}"
            )
            blocks.append(f"{cabecalho}\n{result.text}")
        return "\n\n".join(blocks)


class RetrievalService:
    """
    Pipeline de retrieval, em camadas opcionais:
      1. Busca: só-vetorial (Qdrant) ou híbrida (Qdrant + BM25 via RRF), se
         um BM25Index for passado.
      2. Reranking: se um Reranker for passado, os candidatos (até
         `fetch_k`) são reordenados por um cross-encoder antes do corte
         final em `top_k`.

    Cada camada extra é estritamente opt-in — sem BM25Index nem Reranker,
    o comportamento é idêntico ao retrieval só-vetorial original.
    """

    def __init__(
        self,
        indexer: QdrantIndexer,
        top_k: int = 5,
        bm25_index: Optional[BM25Index] = None,
        reranker: Optional[Reranker] = None,
        fetch_k: int = 20,
    ) -> None:
        self.indexer = indexer
        self.top_k = top_k
        self.bm25_index = bm25_index
        self.reranker = reranker
        self.fetch_k = fetch_k

    def retrieve(
        self,
        query: str,
        cnpj: Optional[str] = None,
        statement_type: Optional[str] = None,
    ) -> RetrievedContext:
        # Se vamos reranquear depois, busca um conjunto maior de candidatos
        # (fetch_k) pro reranker ter material pra trabalhar; senão, já busca
        # direto o tamanho final (top_k).
        candidate_limit = self.fetch_k if self.reranker else self.top_k

        if self.bm25_index is None or self.bm25_index.is_empty():
            candidates = self.indexer.search(
                query, limit=candidate_limit, cnpj=cnpj, statement_type=statement_type
            )
        else:
            candidates = self._hybrid_search(query, cnpj, statement_type, limit=candidate_limit)

        if self.reranker and candidates:
            candidates = self._rerank(query, candidates)

        return RetrievedContext(results=candidates[: self.top_k])

    def _rerank(self, query: str, candidates: list[SearchResult]) -> list[SearchResult]:
        scores = self.reranker.rerank(query, [c.text for c in candidates])
        paired = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
        return [
            SearchResult(score=score, text=candidate.text, metadata=candidate.metadata)
            for candidate, score in paired
        ]

    def _hybrid_search(
        self, query: str, cnpj: Optional[str], statement_type: Optional[str], limit: int
    ) -> list[SearchResult]:
        vector_hits = self.indexer.search(
            query, limit=self.fetch_k, cnpj=cnpj, statement_type=statement_type
        )
        bm25_hits = self.bm25_index.search(query, limit=self.fetch_k)

        # Aplica os mesmos filtros de metadado na busca por palavra-chave,
        # pra busca híbrida respeitar cnpj/statement_type também.
        bm25_hits = [
            (chunk_id, score, meta)
            for chunk_id, score, meta in bm25_hits
            if (cnpj is None or meta.get("cnpj") == cnpj)
            and (statement_type is None or meta.get("statement_type") == statement_type)
        ]

        vector_ranking = [r.metadata["chunk_id"] for r in vector_hits]
        bm25_ranking = [chunk_id for chunk_id, _, _ in bm25_hits]
        fused_ids = reciprocal_rank_fusion([vector_ranking, bm25_ranking])[:limit]

        by_id: dict[str, SearchResult] = {r.metadata["chunk_id"]: r for r in vector_hits}
        bm25_by_id = {chunk_id: (score, meta) for chunk_id, score, meta in bm25_hits}
        # Scores do BM25 podem ser negativos (IDF negativo, ver bm25_index.py) —
        # pra exibição (0 a 1, como o score de cosseno do Qdrant), tratamos
        # qualquer score negativo como 0 antes de normalizar.
        max_bm25_score = max((max(score, 0.0) for _, score, _ in bm25_hits), default=0.0)

        fused_results: list[SearchResult] = []
        for chunk_id in fused_ids:
            if chunk_id in by_id:
                fused_results.append(by_id[chunk_id])
            elif chunk_id in bm25_by_id:
                raw_score, meta = bm25_by_id[chunk_id]
                normalized_score = max(raw_score, 0.0) / max_bm25_score if max_bm25_score > 0 else 0.0
                fused_results.append(
                    SearchResult(score=normalized_score, text=meta.get("text", ""), metadata=meta)
                )

        return fused_results
