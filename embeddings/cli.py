"""
CLI para gerar embeddings e indexar os chunks da CVM no Qdrant.

Exemplo (Qdrant local embarcado, persistido em disco — bom para começar):
    python -m embeddings.cli --doc-type dfp --qdrant-path data/qdrant_local

Exemplo (Qdrant rodando em Docker ou Qdrant Cloud):
    python -m embeddings.cli --doc-type dfp --qdrant-url http://localhost:6333

OBS: usa BGEM3Embedder (BAAI/bge-m3), que baixa o modelo do Hugging Face na
primeira execução. Rode numa máquina com internet livre (ou no Colab, com
GPU) — não dentro de um sandbox com allowlist de domínios.
"""
from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(
        description="Gera embeddings (bge-m3) e indexa os chunks da CVM no Qdrant."
    )
    parser.add_argument("--doc-type", choices=["dfp", "itr"], required=True)
    parser.add_argument(
        "--processed-dir", type=Path, default=None,
        help="Override do diretório de Parquets processados (default: data/processed/cvm/<doc-type>)",
    )
    parser.add_argument(
        "--qdrant-path", type=Path, default=None,
        help="Caminho local para o Qdrant embarcado (modo dev, sem servidor)",
    )
    parser.add_argument(
        "--qdrant-url", type=str, default=None,
        help="URL de um servidor Qdrant real (Docker local ou Qdrant Cloud). Tem prioridade sobre --qdrant-path.",
    )
    parser.add_argument("--collection", type=str, default="cvm_demonstracoes")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--bm25-path", type=Path, default=None,
        help="Caminho onde salvar o índice BM25 (busca por palavra-chave). Default: data/bm25_index.pkl",
    )
    parser.add_argument(
        "--skip-parecer", action="store_true",
        help="Não inclui os chunks do Relatório do Auditor Independente (parecer) na indexação",
    )
    parser.add_argument(
        "--recreate-collection", action="store_true",
        help="Apaga e recria a collection do zero antes de indexar",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    logger = logging.getLogger("embeddings.cli")

    if args.qdrant_url:
        client = QdrantClient(url=args.qdrant_url)
        logger.info("Conectando a servidor Qdrant remoto: %s", args.qdrant_url)
    else:
        local_path = args.qdrant_path or (PROCESSED_DIR.parent.parent / "qdrant_local")
        client = QdrantClient(path=str(local_path))
        logger.info("Usando Qdrant local embarcado em: %s", local_path)

    processed_dir = args.processed_dir or (PROCESSED_DIR / args.doc_type)
    logger.info("Carregando chunks processados de %s", processed_dir)
    statement_chunks = load_parquet_dir_chunks(processed_dir, doc_type=args.doc_type)

    parecer_chunks = []
    if not args.skip_parecer:
        logger.info("Carregando chunks do Relatório do Auditor Independente (parecer)...")
        parecer_chunks = load_parecer_parquet_dir_chunks(processed_dir, doc_type=args.doc_type)

    chunks = statement_chunks + parecer_chunks
    logger.info(
        "Total combinado: %d chunks de demonstração + %d chunks de parecer = %d chunks",
        len(statement_chunks), len(parecer_chunks), len(chunks),
    )

    if not chunks:
        logger.warning(
            "Nenhum chunk encontrado em %s — rode o download e o process antes "
            "(ver ingestion.cli) e confirme que os Parquets existem.",
            processed_dir,
        )
        return 1

    logger.info("Carregando modelo de embedding (BAAI/bge-m3)...")
    embedder = BGEM3Embedder()

    indexer = QdrantIndexer(client=client, embedder=embedder, collection_name=args.collection)
    indexer.ensure_collection(recreate=args.recreate_collection)

    total = indexer.index_chunks(chunks, batch_size=args.batch_size)
    logger.info("Indexação no Qdrant concluída: %d chunks na collection '%s'.", total, args.collection)

    bm25_path = args.bm25_path or (PROCESSED_DIR.parent.parent / "bm25_index.pkl")
    logger.info("Construindo índice BM25 (busca por palavra-chave)...")
    bm25_index = BM25Index()
    bm25_index.build(chunks)
    bm25_index.save(bm25_path)
    logger.info("Índice BM25 salvo em %s.", bm25_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
