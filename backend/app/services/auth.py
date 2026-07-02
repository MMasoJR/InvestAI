"""
Serviço de autenticação: hashing de senha (bcrypt) e JWT.

A chave secreta (`secret_key` em Settings) deve ser uma string longa e
aleatória em produção — nunca use o valor default. Gere uma com:
    python -c "import secrets; print(secrets.token_hex(32))"
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.app.config import get_settings

# argon2 é mais moderno que bcrypt, sem o limite de 72 bytes que o bcrypt
# tem e sem os conflitos de versão entre passlib e bcrypt >= 4.x.
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """Retorna o user_id se o token for válido, None caso contrário."""
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
