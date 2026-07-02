"""Testes unitários do ConversationStore — sem FastAPI, direto no banco (SQLite em memória)."""
from __future__ import annotations

from backend.app.services.conversation_store import ConversationStore


def test_get_or_create_creates_new_conversation_when_none_given(db_session) -> None:
    store = ConversationStore(db_session)
    conversation = store.get_or_create(None)

    assert conversation.id is not None
    assert store.get(conversation.id) is not None


def test_get_or_create_returns_existing_conversation(db_session) -> None:
    store = ConversationStore(db_session)
    created = store.get_or_create(None)

    fetched = store.get_or_create(created.id)

    assert fetched.id == created.id


def test_get_or_create_with_unknown_id_creates_new_one(db_session) -> None:
    store = ConversationStore(db_session)
    conversation = store.get_or_create("id-que-nao-existe")

    assert conversation.id != "id-que-nao-existe"
    assert store.get(conversation.id) is not None


def test_add_message_and_get_history_preserves_order(db_session) -> None:
    store = ConversationStore(db_session)
    conversation = store.get_or_create(None)

    store.add_message(conversation.id, role="user", content="primeira pergunta")
    store.add_message(conversation.id, role="assistant", content="primeira resposta", sources=[{"a": 1}])
    store.add_message(conversation.id, role="user", content="segunda pergunta")

    history = store.get_history(conversation.id, limit=10)

    assert [m.role for m in history] == ["user", "assistant", "user"]
    assert history[0].content == "primeira pergunta"
    assert history[1].sources == [{"a": 1}]


def test_get_history_respects_limit(db_session) -> None:
    store = ConversationStore(db_session)
    conversation = store.get_or_create(None)
    for i in range(5):
        store.add_message(conversation.id, role="user", content=f"mensagem {i}")

    history = store.get_history(conversation.id, limit=2)

    assert len(history) == 2
    assert history[-1].content == "mensagem 4"


def test_get_history_for_unknown_conversation_returns_empty_list(db_session) -> None:
    store = ConversationStore(db_session)
    assert store.get_history("id-que-nao-existe") == []


def test_list_conversations_orders_most_recent_first(db_session) -> None:
    store = ConversationStore(db_session)
    first = store.get_or_create(None)
    second = store.get_or_create(None)

    conversations = store.list_conversations()

    assert conversations[0].id == second.id
    assert conversations[1].id == first.id
