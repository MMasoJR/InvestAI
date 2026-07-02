"""
Camada de reranking: reordena os candidatos trazidos pela busca (híbrida ou
só-vetorial) usando um modelo que avalia o PAR (pergunta, documento) — mais
preciso que comparar vetores isolados, mas também mais caro, por isso só é
aplicado nos top-N candidatos, não na base inteira.

Como em embeddings/embedder.py e backend/app/services/llm.py, definido como
Protocol — assim é possível trocar de modelo/provedor sem alterar o resto
do pipeline.
"""
from __future__ import annotations

from typing import Protocol, Sequence


class Reranker(Protocol):
    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """Retorna um score de relevância por documento, na MESMA ORDEM da entrada."""
        ...


class CrossEncoderReranker:
    """
    Reranker de produção: cross-encoder BAAI/bge-reranker-v2-m3, multilíngue.

    Diferença de um embedder normal: em vez de gerar um vetor pra pergunta e
    outro pro documento e comparar depois, o cross-encoder recebe os dois
    JUNTOS e julga a relevância diretamente — mais preciso, mais lento. Por
    isso ele entra só depois da busca híbrida já ter filtrado os candidatos.

    O import de sentence-transformers/torch é tardio (só ao instanciar esta
    classe), e a primeira execução baixa o modelo do Hugging Face Hub — rode
    numa máquina com internet livre, não num sandbox com allowlist de domínios.
    """

    MODEL_NAME = "BAAI/bge-reranker-v2-m3"

    def __init__(self, device: str | None = None) -> None:
        from sentence_transformers import CrossEncoder  # import tardio

        self._model = CrossEncoder(self.MODEL_NAME, device=device)

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        pairs = [[query, doc] for doc in documents]
        scores = self._model.predict(pairs)
        return [float(s) for s in scores]
