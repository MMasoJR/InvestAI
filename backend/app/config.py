"""
Configurações da API, lidas de variáveis de ambiente (ou de um arquivo .env
na raiz do projeto). Centralizar aqui evita "números mágicos" espalhados
pelo código e facilita trocar de ambiente (dev local -> produção) sem
alterar nenhuma linha de código, só variáveis de ambiente.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVESTAI_", env_file=".env", extra="ignore")

    # Se qdrant_url estiver definido, conecta a um servidor real (Docker/Cloud).
    # Caso contrário, usa o Qdrant local embarcado em qdrant_local_path.
    qdrant_url: Optional[str] = None
    qdrant_api_key: Optional[str] = None
    qdrant_local_path: str = "data/qdrant_local"
    collection_name: str = "cvm_demonstracoes"

    top_k: int = 5
    llm_model: str = "claude-sonnet-4-6"

    # Se database_url estiver definida, conecta a um Postgres real, ex:
    #   postgresql+psycopg2://usuario:senha@localhost:5432/investai
    # Caso contrário, usa SQLite em arquivo local (data/investai.db) — ótimo
    # pra desenvolver sem precisar instalar/configurar um servidor Postgres.
    database_url: Optional[str] = None
    history_limit: int = 10  # quantas mensagens anteriores entram no contexto do LLM

    bm25_index_path: str = "data/bm25_index.pkl"
    enable_reranking: bool = True
    brapi_token: Optional[str] = None  # token gratuito em brapi.dev; sem ele, só 4 tickers funcionam

    # Autenticação JWT
    secret_key: str = "TROQUE_ESTA_CHAVE_ANTES_DE_DEPLOY"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 dias


@lru_cache
def get_settings() -> Settings:
    return Settings()
