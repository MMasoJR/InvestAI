"""Testes dos endpoints GET /conversations e GET /conversations/{id}."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def _token(client: TestClient, email: str = "conv_test@example.com") -> str:
    r = client.post("/auth/register", json={"email": email, "password": "senha12345"})
    if r.status_code == 409:
        r = client.post("/auth/login", json={"email": email, "password": "senha12345"})
    return r.json()["access_token"]


def test_list_conversations_empty(override_get_db) -> None:
    client = TestClient(app)
    token = _token(client)
    response = client.get("/conversations", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_list_conversations_without_token_returns_401(override_get_db) -> None:
    client = TestClient(app)
    response = client.get("/conversations")
    assert response.status_code == 401


def test_get_conversation_not_found(override_get_db) -> None:
    client = TestClient(app)
    token = _token(client, "notfound@example.com")
    response = client.get("/conversations/id-que-nao-existe", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_list_and_get_conversation_after_creation(db_session, override_get_db) -> None:
    from backend.app.services.conversation_store import ConversationStore
    from backend.app.services.user_store import UserStore

    client = TestClient(app)
    token = _token(client, "detail_test@example.com")

    # Cria a conversa via db_session (mesmo banco de teste que o endpoint usa)
    user = UserStore(db_session).get_by_email("detail_test@example.com")
    store = ConversationStore(db_session)
    conversation = store.get_or_create(None, user_id=user.id)
    store.add_message(conversation.id, role="user", content="Qual o ativo total da empresa?")
    store.add_message(
        conversation.id, role="assistant", content="O ativo total é X.", sources=[{"company_name": "Y"}]
    )
    db_session.commit()

    list_response = client.get("/conversations", headers={"Authorization": f"Bearer {token}"})
    assert list_response.status_code == 200
    summaries = list_response.json()
    assert len(summaries) == 1
    assert summaries[0]["message_count"] == 2
    assert summaries[0]["title"].startswith("Qual o ativo total")

    detail_response = client.get(
        f"/conversations/{conversation.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][1]["sources"] == [{"company_name": "Y"}]
