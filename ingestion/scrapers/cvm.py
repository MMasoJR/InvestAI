"""
Scraper profissional para os dados abertos de Companhias Abertas da CVM:
DFP (Demonstrações Financeiras Padronizadas) e ITR (Informações Trimestrais).

Fonte oficial:
    https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp
    https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr

Padrão de URL confirmado no portal (ex.):
    https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2023.zip
    https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2023.zip

Uso típico:
    import asyncio
    from ingestion.scrapers.cvm import CVMClient

    client = CVMClient()
    asyncio.run(client.sync_all(doc_type="dfp", start_year=2015, end_year=2025))

    for year in range(2015, 2026):
        client.process_doc_type_year("dfp", year)
"""
from __future__ import annotations

import asyncio
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import httpx
import pandas as pd

from ingestion.config import (
    BACKOFF_BASE_SECONDS,
    CVM_BASE_URL,
    DOC_TYPES,
    MAX_CONCURRENT_DOWNLOADS,
    MAX_RETRIES,
    PROCESSED_DIR,
    RAW_DIR,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)

logger = logging.getLogger("ingestion.cvm")


@dataclass(frozen=True)
class DownloadResult:
    """Resultado de uma tentativa de download de um ZIP (doc_type, ano)."""

    doc_type: str
    year: int
    zip_path: Optional[Path]
    skipped: bool
    error: Optional[str] = None


class CVMDownloadError(RuntimeError):
    """Erro irrecuperável ao processar um arquivo baixado da CVM."""


class CVMClient:
    """
    Cliente responsável por baixar, extrair e normalizar os dados abertos
    de Companhias Abertas da CVM (DFP/ITR).

    Princípios de design:
      - Idempotente: arquivos já baixados não são baixados de novo.
      - Educado com o servidor: concorrência limitada + backoff exponencial.
      - Resiliente: 404 (ano sem dado publicado) não é tratado como falha grave.
      - Testável: toda a lógica de rede passa por um httpx.AsyncClient injetável.
    """

    def __init__(
        self,
        raw_dir: Path = RAW_DIR,
        processed_dir: Path = PROCESSED_DIR,
        max_concurrent_downloads: int = MAX_CONCURRENT_DOWNLOADS,
    ) -> None:
        self.raw_dir = raw_dir
        self.processed_dir = processed_dir
        self._semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Construção de caminhos e URLs
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_url(doc_type: str, year: int) -> str:
        if doc_type not in DOC_TYPES:
            raise ValueError(
                f"Tipo de documento desconhecido: {doc_type!r}. "
                f"Opções válidas: {list(DOC_TYPES)}"
            )
        code = DOC_TYPES[doc_type].code
        filename = f"{doc_type}_cia_aberta_{year}.zip"
        return f"{CVM_BASE_URL}/{code}/DADOS/{filename}"

    def _zip_path_for(self, doc_type: str, year: int) -> Path:
        return self.raw_dir / doc_type / f"{doc_type}_cia_aberta_{year}.zip"

    # ------------------------------------------------------------------ #
    # Download com retry/backoff exponencial
    # ------------------------------------------------------------------ #

    async def _download_one(
        self, client: httpx.AsyncClient, doc_type: str, year: int
    ) -> DownloadResult:
        url = self._build_url(doc_type, year)
        dest = self._zip_path_for(doc_type, year)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists() and dest.stat().st_size > 0:
            logger.info("Já existe localmente, pulando: %s", dest.name)
            return DownloadResult(doc_type, year, dest, skipped=True)

        async with self._semaphore:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    logger.info(
                        "Baixando %s (tentativa %d/%d)", url, attempt, MAX_RETRIES
                    )
                    response = await client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

                    if response.status_code == 404:
                        logger.warning(
                            "Sem dados publicados para %s/%d (HTTP 404) — ano "
                            "provavelmente ainda não entregue ou fora do período.",
                            doc_type, year,
                        )
                        return DownloadResult(doc_type, year, None, skipped=True, error="404")

                    response.raise_for_status()

                    tmp_path = dest.with_suffix(".zip.part")
                    tmp_path.write_bytes(response.content)

                    if not zipfile.is_zipfile(tmp_path):
                        tmp_path.unlink(missing_ok=True)
                        raise CVMDownloadError(
                            f"Conteúdo baixado de {url} não é um ZIP válido."
                        )

                    tmp_path.replace(dest)
                    logger.info(
                        "Download concluído: %s (%.1f KB)",
                        dest.name, dest.stat().st_size / 1024,
                    )
                    return DownloadResult(doc_type, year, dest, skipped=False)

                except (httpx.HTTPError, CVMDownloadError) as exc:
                    wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "Falha ao baixar %s (tentativa %d/%d): %s. Retentando em %.1fs",
                        url, attempt, MAX_RETRIES, exc, wait,
                    )
                    if attempt == MAX_RETRIES:
                        return DownloadResult(
                            doc_type, year, None, skipped=False, error=str(exc)
                        )
                    await asyncio.sleep(wait)

        # Inalcançável na prática (o loop sempre retorna ou levanta), mas
        # mantido por segurança/tipagem.
        return DownloadResult(doc_type, year, None, skipped=False, error="unknown")

    async def sync_years(self, doc_type: str, years: Iterable[int]) -> list[DownloadResult]:
        """Baixa, de forma concorrente (porém limitada e educada), vários anos."""
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            tasks = [self._download_one(client, doc_type, year) for year in years]
            return await asyncio.gather(*tasks)

    async def sync_all(
        self, doc_type: str, start_year: int, end_year: int
    ) -> list[DownloadResult]:
        """Baixa todos os anos disponíveis de um tipo de documento em um intervalo."""
        cfg = DOC_TYPES[doc_type]
        first_valid_year = max(start_year, cfg.first_year)
        years = range(first_valid_year, end_year + 1)
        results = await self.sync_years(doc_type, years)

        ok = [r for r in results if r.zip_path is not None]
        real_failures = [r for r in results if r.zip_path is None and r.error not in (None, "404")]

        logger.info(
            "Sincronização de %s concluída: %d arquivos disponíveis, %d falhas reais.",
            doc_type.upper(), len(ok), len(real_failures),
        )
        for r in real_failures:
            logger.error("Falha definitiva em %s/%d: %s", r.doc_type, r.year, r.error)

        return results

    # ------------------------------------------------------------------ #
    # Extração e parsing
    # ------------------------------------------------------------------ #

    def extract(self, zip_path: Path) -> Path:
        """Extrai um ZIP da CVM para uma subpasta dedicada e retorna o diretório."""
        extract_dir = zip_path.parent / zip_path.stem
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        logger.info("Extraído %s -> %s", zip_path.name, extract_dir)
        return extract_dir

    @staticmethod
    def read_cvm_csv(csv_path: Path) -> pd.DataFrame:
        """
        Lê um CSV da CVM respeitando o padrão real desses arquivos:
        encoding latin-1, separador ';' e decimal ','.

        Tipos não são convertidos aqui de propósito — normalização de
        schema (datas, floats, categorias) é responsabilidade da próxima
        etapa do pipeline (camada de processamento/chunking).
        """
        return pd.read_csv(
            csv_path,
            sep=";",
            encoding="latin-1",
            decimal=",",
            dtype=str,
            low_memory=False,
        )

    def process_doc_type_year(self, doc_type: str, year: int) -> dict[str, Path]:
        """
        Extrai o ZIP de um ano (se ainda não extraído) e converte cada CSV
        interno para Parquet, particionado por tipo de documento e ano.

        Levanta FileNotFoundError se o ZIP correspondente ainda não foi
        baixado (rode sync_all/sync_years antes).
        """
        zip_path = self._zip_path_for(doc_type, year)
        if not zip_path.exists():
            raise FileNotFoundError(
                f"ZIP não encontrado em {zip_path}. Rode o download primeiro "
                f"(client.sync_all('{doc_type}', {year}, {year}))."
            )

        extract_dir = self.extract(zip_path)
        out_dir = self.processed_dir / doc_type / str(year)
        out_dir.mkdir(parents=True, exist_ok=True)

        written: dict[str, Path] = {}
        csv_files = sorted(extract_dir.glob("*.csv"))
        if not csv_files:
            logger.warning("Nenhum CSV encontrado dentro de %s", zip_path.name)

        for csv_path in csv_files:
            df = self.read_cvm_csv(csv_path)
            out_path = out_dir / f"{csv_path.stem}.parquet"
            df.to_parquet(out_path, index=False)
            written[csv_path.stem] = out_path
            logger.info(
                "Processado %s -> %s (%d linhas, %d colunas)",
                csv_path.name, out_path.name, len(df), len(df.columns),
            )

        return written
