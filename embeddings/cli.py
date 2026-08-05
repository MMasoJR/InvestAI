"""
CLI para gerar embeddings e indexar os chunks da CVM no Qdrant.

Na primeira execução, gera os chunks dos Parquets (lento, ~20 min) e salva
em cache JSONL. Nas execuções seguintes, carrega do cache (~30 seg).
Use --rebuild-cache para forçar regeneração após novos downloads.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from qdrant_client import QdrantClient

from embeddings.bm25_index import BM25Index
from embeddings.embedder import BGEM3Embedder
from embeddings.qdrant_index import QdrantIndexer
from ingestion.config import PROCESSED_DIR
from processing.chunking.cvm_chunker import load_parquet_dir_chunks
from processing.chunking.cvm_parecer_chunker import load_parecer_parquet_dir_chunks


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gera embeddings e indexa chunks da CVM no Qdrant.")
    parser.add_argument("--doc-type", choices=["dfp", "itr"], required=True)
    parser.add_argument("--processed-dir", type=Path, default=None)
    parser.add_argument("--qdrant-path", type=Path, default=None)
    parser.add_argument("--qdrant-url", type=str, default=None)
    parser.add_argument("--collection", type=str, default="cvm_demonstracoes")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--bm25-path", type=Path, default=None)
    parser.add_argument("--cache-path", type=Path, default=None,
        help="Cache JSONL de chunks. Default: data/chunks_cache_<doc-type>.jsonl")
    parser.add_argument("--rebuild-cache", action="store_true",
        help="Força regeneração dos chunks mesmo que o cache exista")
    parser.add_argument("--skip-parecer", action="store_true")
    parser.add_argument("--recreate-collection", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


class _CachedChunk:
    """Wrapper leve que satisfaz a interface de QdrantIndexer e BM25Index."""
    def __init__(self, data: dict) -> None:
        self._data = data

    @property
    def chunk_id(self) -> str:
        return self._data["chunk_id"]

    @property
    def text(self) -> str:
        return self._data["text"]

    def to_dict(self) -> dict:
        return self._data


def _save_cache(chunks: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            d = chunk.to_dict()
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    logging.getLogger("embeddings.cli").info("Cache salvo: %s (%d chunks)", path, len(chunks))


def _load_cache(path: Path) -> list[_CachedChunk]:
    chunks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(_CachedChunk(json.loads(line)))
    return chunks


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    logger = logging.getLogger("embeddings.cli")

    if args.qdrant_url:
        client = QdrantClient(url=args.qdrant_url)
        logger.info("Conectando a servidor Qdrant: %s", args.qdrant_url)
    else:
        local_path = args.qdrant_path or (PROCESSED_DIR.parent.parent / "qdrant_local")
        client = QdrantClient(path=str(local_path))
        logger.info("Usando Qdrant local em: %s", local_path)

    cache_path = args.cache_path or (PROCESSED_DIR.parent.parent / f"chunks_cache_{args.doc_type}.jsonl")

    if cache_path.exists() and not args.rebuild_cache:
        logger.info("Carregando chunks do cache: %s (use --rebuild-cache para regenerar)", cache_path)
        chunks = _load_cache(cache_path)
        logger.info("Cache carregado: %d chunks", len(chunks))
    else:
        if args.rebuild_cache:
            logger.info("--rebuild-cache: regenerando chunks dos Parquets...")
        else:
            logger.info("Cache não encontrado. Gerando chunks (pode demorar ~20 min)...")

        processed_dir = args.processed_dir or (PROCESSED_DIR / args.doc_type)
        statement_chunks = load_parquet_dir_chunks(processed_dir, doc_type=args.doc_type)

        parecer_chunks = []
        if not args.skip_parecer:
            parecer_chunks = load_parecer_parquet_dir_chunks(processed_dir, doc_type=args.doc_type)

        chunks = statement_chunks + parecer_chunks
        logger.info(
            "Total: %d demonstração + %d parecer = %d chunks",
            len(statement_chunks), len(parecer_chunks), len(chunks),
        )

        if not chunks:
            logger.warning("Nenhum chunk encontrado. Rode o download e o process antes.")
            return 1

        logger.info("Salvando cache em %s...", cache_path)
        _save_cache(chunks, cache_path)

    logger.info("Carregando modelo de embedding (multilingual-e5-large via fastembed)...")
    embedder = BGEM3Embedder()

    indexer = QdrantIndexer(client=client, embedder=embedder, collection_name=args.collection)
    indexer.ensure_collection(recreate=args.recreate_collection)

    total = indexer.index_chunks(chunks, batch_size=args.batch_size)
    logger.info("Indexação concluída: %d chunks em '%s'.", total, args.collection)

    bm25_path = args.bm25_path or (PROCESSED_DIR.parent.parent / "bm25_index.pkl")
    logger.info("Construindo índice BM25...")
    bm25_index = BM25Index()
    bm25_index.build(chunks)
    bm25_index.save(bm25_path)
    logger.info("BM25 salvo em %s.", bm25_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
