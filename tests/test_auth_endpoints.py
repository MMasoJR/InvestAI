"""
Testes de integração dos endpoints de autenticação (/auth/register,
/auth/login, /auth/me) e do controle de acesso em /conversations.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def _register_and_login(client: TestClient, email: str, password: str = "senha_segura_123") -> str:
    """Registra um usuário e retorna o token de acesso."""
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_register_creates_user_and_returns_token(override_get_db) -> None:
    client = TestClient(app)
    response = client.post("/auth/register", json={"email": "test@example.com", "password": "senha123"})

    assert response.status_code == 201
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_register_duplicate_email_returns_409(override_get_db) -> None:
    client = TestClient(app)
    client.post("/auth/register", json={"email": "dup@example.com", "password": "senha123"})
    response = client.post("/auth/register", json={"email": "dup@example.com", "password": "outrasenha"})

    assert response.status_code == 409


def test_register_short_password_returns_422(override_get_db) -> None:
    client = TestClient(app)
    response = client.post("/auth/register", json={"email": "a@b.com", "password": "curta"})
    assert response.status_code == 422


def test_login_valid_credentials_returns_token(override_get_db) -> None:
    client = TestClient(app)
    client.post("/auth/register", json={"email": "login@example.com", "password": "senha123"})
    response = client.post("/auth/login", json={"email": "login@example.com", "password": "senha123"})

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_wrong_password_returns_401(override_get_db) -> None:
    client = TestClient(app)
    client.post("/auth/register", json={"email": "wrong@example.com", "password": "senha123"})
    response = client.post("/auth/login", json={"email": "wrong@example.com", "password": "errada"})

    assert response.status_code == 401


def test_login_nonexistent_email_returns_401(override_get_db) -> None:
    client = TestClient(app)
    response = client.post("/auth/login", json={"email": "nao@existe.com", "password": "qualquer"})
    assert response.status_code == 401


def test_me_with_valid_token_returns_user_info(override_get_db) -> None:
    client = TestClient(app)
    token = _register_and_login(client, "me@example.com")

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert "id" in body


def test_me_without_token_returns_401(override_get_db) -> None:
    client = TestClient(app)
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_with_invalid_token_returns_401(override_get_db) -> None:
    client = TestClient(app)
    response = client.get("/auth/me", headers={"Authorization": "Bearer token.invalido"})
    assert response.status_code == 401


def test_conversations_requires_auth(override_get_db) -> None:
    client = TestClient(app)
    response = client.get("/conversations")
    assert response.status_code == 401


def test_conversations_returns_only_users_own_conversations(override_get_db) -> None:
    from backend.app.dependencies import get_assessor_service
    from backend.app.services.assessor import AssessorService
    from backend.app.services.retrieval import RetrievalService
    from tests.fake_llm import FakeLLMClient

    # Injeta um assessor sem Qdrant real — suficiente pra criar conversas
    class _FakeRetrieval:
        def retrieve(self, *args, **kwargs):
            from backend.app.services.retrieval import RetrievedContext
            return RetrievedContext(results=[])

    assessor = AssessorService(retrieval=_FakeRetrieval(), llm=FakeLLMClient())
    app.dependency_overrides[get_assessor_service] = lambda: assessor

    client = TestClient(app)

    token_a = _register_and_login(client, "user_a@example.com")
    token_b = _register_and_login(client, "user_b@example.com")

    # Usuário A faz uma pergunta (cria uma conversa vinculada a ele)
    client.post(
        "/chat", json={"question": "Pergunta do usuario A"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # Usuário B lista suas conversas — não deve ver a do usuário A
    response = client.get("/conversations", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 200
    assert response.json() == []

    # Usuário A vê a própria conversa
    response_a = client.get("/conversations", headers={"Authorization": f"Bearer {token_a}"})
    assert len(response_a.json()) == 1

    app.dependency_overrides.pop(get_assessor_service, None)


def test_get_conversation_by_other_user_returns_403(db_session, override_get_db) -> None:
    client = TestClient(app)
    token_a = _register_and_login(client, "owner@example.com")
    token_b = _register_and_login(client, "thief@example.com")

    # Cria uma conversa diretamente no banco de TESTE (via db_session da fixture)
    from backend.app.services.conversation_store import ConversationStore
    from backend.app.services.user_store import UserStore

    user_a = UserStore(db_session).get_by_email("owner@example.com")
    store = ConversationStore(db_session)
    conv = store.get_or_create(None, user_id=user_a.id)
    db_session.commit()

    # Usuário B tenta acessar a conversa do usuário A
    response = client.get(f"/conversations/{conv.id}", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 403
