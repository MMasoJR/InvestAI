"""Router de consulta ao histórico de conversas — requer autenticação."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.auth_deps import get_current_user
from backend.app.db import get_db
from backend.app.models.db_models import User
from backend.app.models.schemas import ConversationDetail, ConversationSummary, MessageItem
from backend.app.services.conversation_store import ConversationStore

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _summarize(conversation) -> ConversationSummary:
    first_user_message = next((m for m in conversation.messages if m.role == "user"), None)
    title = conversation.title or (
        first_user_message.content[:60] if first_user_message else "Nova conversa"
    )
    return ConversationSummary(
        id=conversation.id,
        title=title,
        created_at=conversation.created_at,
        message_count=len(conversation.messages),
    )


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConversationSummary]:
    """Lista apenas as conversas do usuário autenticado."""
    store = ConversationStore(db)
    return [_summarize(c) for c in store.list_conversations(user_id=current_user.id)]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationDetail:
    store = ConversationStore(db)
    conversation = store.get(conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    # Garante que o usuário só acessa suas próprias conversas.
    if conversation.user_id and conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acesso negado")

    return ConversationDetail(
        id=conversation.id,
        created_at=conversation.created_at,
        messages=[
            MessageItem(
                role=m.role, content=m.content, sources=m.sources, created_at=m.created_at
            )
            for m in conversation.messages
        ],
    )
