"""
Embedder determinístico para testes: não depende de modelo real, rede ou
GPU. Gera vetores a partir de um hash do texto — textos idênticos geram
vetores idênticos (similaridade 1.0), textos diferentes geram vetores
diferentes. Suficiente para validar a lógica de indexação e busca sem
pagar o custo (tempo/rede) de carregar um modelo de embedding real.
"""
from __future__ import annotations

import hashlib
from typing import Sequence


class FakeEmbedder:
    def __init__(self, dimension: int = 16) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = [b / 255.0 for b in digest[: self._dimension]]
            vectors.append(vector)
        return vectors
