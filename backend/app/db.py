"""
Configuração do banco de dados via SQLAlchemy.

Em produção, defina INVESTAI_DATABASE_URL apontando para um Postgres real:
    postgresql+psycopg2://usuario:senha@localhost:5432/investai

Se não estiver definida, usa SQLite em arquivo local (data/investai.db) —
suficiente para desenvolvimento, sem precisar instalar/configurar nenhum
servidor. O resto do código (models, services) não muda nada entre os dois
bancos — essa é a vantagem de usar um ORM em vez de SQL solto.

Os testes usam SQLite em memória (ver tests/conftest.py / fixtures), nunca
tocando no arquivo real de desenvolvimento.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.app.config import get_settings

Base = declarative_base()


def _resolve_database_url() -> str:
    settings = get_settings()
    return settings.database_url or "sqlite:///data/investai.db"


def make_engine(url: Optional[str] = None) -> Engine:
    resolved_url = url or _resolve_database_url()
    # SQLite precisa desse flag pra ser usado por threads diferentes (o
    # FastAPI/uvicorn pode atender requisições em threads diferentes).
    connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}
    return create_engine(resolved_url, connect_args=connect_args)


engine: Engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """Dependency do FastAPI: abre uma sessão por requisição e garante o fechamento."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
