"""
Camada de acesso a dados das conversas — isola o resto do código de SQL/ORM
direto. Suporta conversas anônimas (user_id=None) e vinculadas a um usuário.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.db_models import Conversation, Message


class ConversationStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, conversation_id: str) -> Optional[Conversation]:
        return self.db.get(Conversation, conversation_id)

    def get_or_create(
        self, conversation_id: Optional[str], user_id: Optional[str] = None
    ) -> Conversation:
        if conversation_id:
            existing = self.get(conversation_id)
            if existing:
                return existing
        conversation = Conversation(user_id=user_id)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: Optional[list] = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id, role=role, content=content, sources=sources
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_history(self, conversation_id: str, limit: int = 10) -> list[Message]:
        conversation = self.get(conversation_id)
        if not conversation:
            return []
        return list(conversation.messages[-limit:])

    def list_conversations(self, user_id: Optional[str] = None) -> list[Conversation]:
        """
        Retorna conversas filtradas por usuário (se user_id fornecido) ou
        todas as conversas anônimas (user_id=None).
        """
        query = self.db.query(Conversation)
        if user_id is not None:
            query = query.filter(Conversation.user_id == user_id)
        else:
            query = query.filter(Conversation.user_id.is_(None))
        return query.order_by(Conversation.created_at.desc()).all()
