"""
Dependency de autenticação para FastAPI.

get_current_user: obrigatória — levanta 401 se o token for inválido/ausente.
get_optional_user: opcional — retorna None se não autenticado (usado em
  endpoints que funcionam tanto para usuários logados quanto anônimos, como
  o chat).
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models.db_models import User
from backend.app.services.auth import decode_access_token
from backend.app.services.user_store import UserStore

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token não fornecido")

    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")

    user = UserStore(db).get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Retorna o usuário se autenticado, ou None se anônimo — sem levantar erro."""
    if not credentials:
        return None
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        return None
    return UserStore(db).get_by_id(user_id)
