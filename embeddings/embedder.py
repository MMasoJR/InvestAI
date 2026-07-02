"""
Camada de geração de embeddings.

Definida como uma interface (Protocol) para que o resto do pipeline
(indexação, busca) nunca dependa de um modelo específico — é possível
trocar o backend (modelo local, API paga, outro modelo multilíngue) sem
tocar em mais nada além deste arquivo.
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """Contrato que qualquer gerador de embeddings deve cumprir."""

    @property
    def dimension(self) -> int:
        """Dimensão dos vetores gerados — necessária para criar a collection no Qdrant."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Recebe uma lista de textos e retorna uma lista de vetores (mesma ordem)."""
        ...


class BGEM3Embedder:
    """
    Embedder de produção: BAAI/bge-m3 via sentence-transformers.

    Multilíngue, open-source, roda local (CPU ou GPU) — boa escolha para
    português + jargão financeiro sem depender de API paga. A justificativa
    completa está no documento de arquitetura do projeto.

    Importante:
      - A primeira execução faz o download do modelo (~2GB) do Hugging
        Face Hub. Rode isso numa máquina com internet livre ou no Colab
        com GPU — não dentro de um sandbox com allowlist de domínios.
      - O import de sentence-transformers/torch é feito de forma tardia
        (dentro de __init__), então só é necessário instalar essas libs
        pesadas se você realmente for usar esta classe. O resto do
        pipeline (chunking, indexação, testes) não depende delas.
    """

    MODEL_NAME = "BAAI/bge-m3"
    _DIMENSION = 1024  # dimensão nativa do bge-m3

    def __init__(self, device: str | None = None, batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer  # import tardio, ver docstring

        self._model = SentenceTransformer(self.MODEL_NAME, device=device)
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._DIMENSION

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,  # essencial: estamos usando distância de cosseno no Qdrant
            show_progress_bar=False,
        )
        return vectors.tolist()
