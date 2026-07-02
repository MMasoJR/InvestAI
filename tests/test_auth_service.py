"""Testes unitários do serviço de autenticação — sem banco, sem rede."""
from __future__ import annotations

import time

from backend.app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    hashed = hash_password("senha_segura_123")
    assert verify_password("senha_segura_123", hashed)
    assert not verify_password("senha_errada", hashed)


def test_hash_is_not_plaintext() -> None:
    hashed = hash_password("minha_senha")
    assert hashed != "minha_senha"
    assert hashed.startswith("$argon2")  # argon2 sempre começa assim


def test_create_and_decode_access_token() -> None:
    token = create_access_token("user-abc-123")
    user_id = decode_access_token(token)
    assert user_id == "user-abc-123"


def test_decode_invalid_token_returns_none() -> None:
    assert decode_access_token("token.invalido.qualquer") is None


def test_decode_tampered_token_returns_none() -> None:
    token = create_access_token("user-abc-123")
    tampered = token[:-5] + "XXXXX"
    assert decode_access_token(tampered) is None
