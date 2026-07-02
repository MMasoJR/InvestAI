"""
Configurações centrais do pipeline de ingestão de dados abertos da CVM.

Fonte oficial dos dados: https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp
                          https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Diretório raiz do projeto (.../cvm_scraper)
BASE_DIR = Path(__file__).resolve().parent.parent

# Onde os ZIPs brutos e os dados processados (Parquet) são gravados.
# Pode ser sobrescrito apontando para outro disco/volume se o projeto crescer.
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw" / "cvm"
PROCESSED_DIR = DATA_DIR / "processed" / "cvm"

CVM_BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"

# Identifica o bot de forma transparente — boa prática ao consumir dados públicos.
USER_AGENT = (
    "investai-ingestion-bot/1.0 "
    "(uso pessoal/academico; contato: marcelomasojunior@gmail.com)"
)


@dataclass(frozen=True)
class DocTypeConfig:
    """Configuração de um tipo de documento da CVM (DFP, ITR, ...)."""

    code: str       # código usado na URL, ex: "DFP", "ITR"
    first_year: int  # primeiro ano com dados disponíveis no portal


# Anos iniciais confirmados no portal de dados abertos da CVM em jun/2026.
DOC_TYPES: dict[str, DocTypeConfig] = {
    "dfp": DocTypeConfig(code="DFP", first_year=2010),
    "itr": DocTypeConfig(code="ITR", first_year=2011),
}

# Política de requisições HTTP
REQUEST_TIMEOUT_SECONDS = 60
MAX_CONCURRENT_DOWNLOADS = 3
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 2.0
