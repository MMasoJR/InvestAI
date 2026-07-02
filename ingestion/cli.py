"""
Interface de linha de comando do pipeline de ingestão CVM.

Exemplos:
    python -m ingestion.cli download --doc-type dfp --start-year 2015 --end-year 2025
    python -m ingestion.cli process  --doc-type dfp --start-year 2015 --end-year 2025
    python -m ingestion.cli download --doc-type itr --start-year 2020 --end-year 2026 -v
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ingestion.scrapers.cvm import CVMClient


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pipeline de ingestão de dados abertos da CVM (DFP/ITR)."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Ativa logs em modo debug"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--doc-type", choices=["dfp", "itr"], required=True)
    common.add_argument("--start-year", type=int, required=True)
    common.add_argument("--end-year", type=int, required=True)

    subparsers.add_parser(
        "download", parents=[common], help="Baixa os ZIPs de um intervalo de anos"
    )
    subparsers.add_parser(
        "process",
        parents=[common],
        help="Extrai e converte os CSVs já baixados para Parquet",
    )

    return parser


async def _run_download(args: argparse.Namespace) -> int:
    client = CVMClient()
    results = await client.sync_all(args.doc_type, args.start_year, args.end_year)
    real_failures = [
        r for r in results if r.zip_path is None and r.error not in (None, "404")
    ]
    return 1 if real_failures else 0


def _run_process(args: argparse.Namespace) -> int:
    client = CVMClient()
    logger = logging.getLogger("ingestion.cli")
    exit_code = 0
    for year in range(args.start_year, args.end_year + 1):
        try:
            client.process_doc_type_year(args.doc_type, year)
        except FileNotFoundError as exc:
            logger.warning(str(exc))
            exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "download":
        return asyncio.run(_run_download(args))
    if args.command == "process":
        return _run_process(args)

    parser.error(f"Comando desconhecido: {args.command}")
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
