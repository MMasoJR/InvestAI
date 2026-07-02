"""
Camada de indexação e busca vetorial usando Qdrant.

Funciona tanto em "modo local" (sem servidor — QdrantClient(path=...), ótimo
para desenvolvimento e testes) quanto contra um servidor real (Docker local
ou Qdrant Cloud — QdrantClient(url=..., api_key=...)). O resto do código é
idêntico nos dois casos; só muda como o QdrantClient é construído.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from embeddings.embedder import Embedder
from processing.chunking.cvm_chunker import StatementChunk

logger = logging.getLogger("embeddings.qdrant_index")

# Namespace fixo (gerado uma única vez) para criar IDs determinísticos a
# partir do chunk_id. Isso torna a indexação idempotente: reindexar o mesmo
# chunk sobrescreve o ponto existente em vez de criar uma duplicata.
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "investai.cvm.chunks")


def _point_id_for(chunk_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, chunk_id))


@dataclass(frozen=True)
class SearchResult:
    """Resultado de uma busca semântica: score de similaridade + chunk completo."""

    score: float
    text: str
    metadata: dict


class QdrantIndexer:
    """Responsável por criar a collection, indexar chunks e buscar por similaridade."""

    def __init__(
        self,
        client: QdrantClient,
        embedder: Embedder,
        collection_name: str = "cvm_demonstracoes",
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.collection_name = collection_name

    def ensure_collection(self, recreate: bool = False) -> None:
        """Cria a collection se ela não existir (ou recria, se recreate=True)."""
        exists = self.client.collection_exists(self.collection_name)

        if exists and recreate:
            self.client.delete_collection(self.collection_name)
            exists = False

        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=qmodels.VectorParams(
                    size=self.embedder.dimension,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            logger.info(
                "Collection '%s' criada (dim=%d, distância=cosseno)",
                self.collection_name, self.embedder.dimension,
            )
        else:
            logger.info("Collection '%s' já existe, reaproveitando", self.collection_name)

    def index_chunks(self, chunks: list[StatementChunk], batch_size: int = 32) -> int:
        """
        Embeda e indexa os chunks em lotes (upsert idempotente — reindexar
        os mesmos chunks não cria duplicatas). Retorna o total indexado.
        """
        total = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = self.embedder.embed([c.text for c in batch])

            points = [
                qmodels.PointStruct(
                    id=_point_id_for(chunk.chunk_id),
                    vector=vector,
                    payload=chunk.to_dict(),
                )
                for chunk, vector in zip(batch, vectors)
            ]
            self.client.upsert(collection_name=self.collection_name, points=points)
            total += len(points)
            logger.info("Indexados %d/%d chunks", total, len(chunks))

        return total

    def search(
        self,
        query: str,
        limit: int = 5,
        cnpj: Optional[str] = None,
        statement_type: Optional[str] = None,
    ) -> list[SearchResult]:
        """
        Busca por similaridade semântica. Filtros por metadado são opcionais
        e compostos com AND (ex.: cnpj + statement_type juntos restringem
        a busca a uma demonstração específica de uma empresa específica).
        """
        query_vector = self.embedder.embed([query])[0]

        must_conditions = []
        if cnpj:
            must_conditions.append(
                qmodels.FieldCondition(key="cnpj", match=qmodels.MatchValue(value=cnpj))
            )
        if statement_type:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="statement_type", match=qmodels.MatchValue(value=statement_type)
                )
            )
        query_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
        )

        return [
            SearchResult(score=hit.score, text=hit.payload.get("text", ""), metadata=hit.payload)
            for hit in response.points
        ]
