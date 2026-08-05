"""
Camada de geração de embeddings via fastembed (ONNX Runtime).
Sem PyTorch, sem DLL issues no Windows.

Modelo padrão: intfloat/multilingual-e5-large
  - 1024 dimensões (igual ao bge-m3 original do projeto)
  - Multilíngue, suporta português
  - ~1.2GB de download na primeira execução
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class BGEM3Embedder:
    MODEL_NAME = "intfloat/multilingual-e5-large"
    _DIMENSION = 1024

    def __init__(self, batch_size: int = 32) -> None:
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=self.MODEL_NAME)
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._DIMENSION

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        embeddings = list(self._model.embed(texts, batch_size=self._batch_size))
        return [e.tolist() for e in embeddings]


class BGEM3EmbedderTorch:
    """Alternativo com PyTorch — use no Colab/Linux com GPU."""
    MODEL_NAME = "BAAI/bge-m3"
    _DIMENSION = 1024

    def __init__(self, device: str | None = None, batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.MODEL_NAME, device=device)
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._DIMENSION

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts), batch_size=self._batch_size,
            normalize_embeddings=True, show_progress_bar=False,
        )
        return vectors.tolist()
