"""
Fixtures compartilhadas de teste.

`db_session`: cria um banco SQLite em memória novo a cada teste (isolado),
usando StaticPool para garantir que a mesma conexão/dado seja reaproveitada
entre múltiplas sessões dentro do mesmo teste — sem isso, cada `Session()`
nova abriria um banco em memória vazio diferente.

`override_get_db`: registra esse banco de teste como a dependency `get_db`
da aplicação FastAPI, e desfaz a sobreposição ao final do teste.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_db
from backend.app.main import app


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def override_get_db(db_session):
    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)
