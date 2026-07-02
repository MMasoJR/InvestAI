"""
Testes unitários do CVMClient.

Nenhum teste aqui faz chamada de rede real — todas as respostas HTTP são
simuladas via httpx.MockTransport. Isso permite validar toda a lógica
(URLs, retry, idempotência, parsing) de forma rápida e determinística,
sem depender da disponibilidade do servidor da CVM.
"""
from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import httpx

from ingestion.scrapers.cvm import CVMClient


def _fake_zip_bytes(inner_filename: str = "dfp_cia_aberta_BPA_con_2023.csv") -> bytes:
    """Gera, em memória, um ZIP com a mesma 'forma' de um ZIP real da CVM."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            inner_filename,
            "CNPJ_CIA;DENOM_CIA;VL_CONTA\n"
            "11.222.333/0001-44;EMPRESA TESTE S.A.;1000,50\n",
        )
    return buffer.getvalue()


def test_build_url_dfp() -> None:
    url = CVMClient._build_url("dfp", 2023)
    assert url == (
        "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2023.zip"
    )


def test_build_url_itr() -> None:
    url = CVMClient._build_url("itr", 2024)
    assert url == (
        "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2024.zip"
    )


def test_download_one_success(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_fake_zip_bytes())

    transport = httpx.MockTransport(handler)
    client = CVMClient(raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed")

    async def _run() -> None:
        async with httpx.AsyncClient(transport=transport) as http_client:
            return await client._download_one(http_client, "dfp", 2023)

    result = asyncio.run(_run())
    assert result.zip_path is not None
    assert result.zip_path.exists()
    assert not result.skipped
    assert result.error is None


def test_download_one_skips_existing_file(tmp_path: Path) -> None:
    client = CVMClient(raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed")
    existing = client._zip_path_for("dfp", 2023)
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(_fake_zip_bytes())

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            "Não deveria fazer nenhuma requisição de rede para um arquivo já existente"
        )

    transport = httpx.MockTransport(handler)

    async def _run():
        async with httpx.AsyncClient(transport=transport) as http_client:
            return await client._download_one(http_client, "dfp", 2023)

    result = asyncio.run(_run())
    assert result.skipped is True


def test_download_one_handles_404_gracefully(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = CVMClient(raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed")

    async def _run():
        async with httpx.AsyncClient(transport=transport) as http_client:
            return await client._download_one(http_client, "itr", 2099)

    result = asyncio.run(_run())
    assert result.zip_path is None
    assert result.error == "404"


def test_download_one_retries_then_fails(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    client = CVMClient(raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed")

    async def _run():
        async with httpx.AsyncClient(transport=transport) as http_client:
            return await client._download_one(http_client, "dfp", 2023)

    result = asyncio.run(_run())
    assert result.zip_path is None
    assert result.error is not None
    assert call_count["n"] == 4  # MAX_RETRIES


def test_process_doc_type_year_converts_csv_to_parquet(tmp_path: Path) -> None:
    client = CVMClient(raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed")
    zip_path = client._zip_path_for("dfp", 2023)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(_fake_zip_bytes())

    written = client.process_doc_type_year("dfp", 2023)

    assert len(written) == 1
    parquet_path = next(iter(written.values()))
    assert parquet_path.exists()
    assert parquet_path.suffix == ".parquet"


def test_process_doc_type_year_raises_if_not_downloaded(tmp_path: Path) -> None:
    client = CVMClient(raw_dir=tmp_path / "raw", processed_dir=tmp_path / "processed")
    try:
        client.process_doc_type_year("dfp", 2099)
        raised = False
    except FileNotFoundError:
        raised = True
    assert raised
