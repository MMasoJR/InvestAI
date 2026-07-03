"""Router do endpoint principal: conversa com o assessor de investimentos."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.auth_deps import get_optional_user
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.dependencies import get_assessor_service
from backend.app.models.db_models import User
from backend.app.models.schemas import ChatRequest, ChatResponse, SourceItem
from backend.app.services.assessor import AssessorService
from backend.app.services.conversation_store import ConversationStore

router = APIRouter(prefix="/chat", tags=["chat"])

logger = logging.getLogger("backend.routers.chat")


def _history_as_messages(store: ConversationStore, conversation_id: str) -> list[dict]:
    limit = get_settings().history_limit
    return [{"role": m.role, "content": m.content} for m in store.get_history(conversation_id, limit=limit)]


def _get_user_id(current_user: Optional[User]) -> Optional[str]:
    return current_user.id if current_user else None


@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    assessor: AssessorService = Depends(get_assessor_service),
    current_user: Optional[User] = Depends(get_optional_user),
) -> ChatResponse:
    store = ConversationStore(db)
    conversation = store.get_or_create(request.conversation_id, user_id=_get_user_id(current_user))
    history = _history_as_messages(store, conversation.id)
    store.add_message(conversation.id, role="user", content=request.question)

    result = assessor.ask(
        request.question,
        cnpj=request.cnpj,
        statement_type=request.statement_type,
        history=history,
    )

    store.add_message(conversation.id, role="assistant", content=result.answer, sources=result.sources)

    return ChatResponse(
        answer=result.answer,
        sources=[SourceItem(**s) for s in result.sources],
        conversation_id=conversation.id,
    )


@router.post("/stream")
def chat_stream(
    request: ChatRequest,
    db: Session = Depends(get_db),
    assessor: AssessorService = Depends(get_assessor_service),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Versão em streaming do mesmo endpoint.
    Aceita autenticação opcional — conversas de usuários logados ficam
    vinculadas ao seu perfil; conversas anônimas continuam funcionando.
    """
    store = ConversationStore(db)
    conversation = store.get_or_create(request.conversation_id, user_id=_get_user_id(current_user))
    history = _history_as_messages(store, conversation.id)
    store.add_message(conversation.id, role="user", content=request.question)

    def event_generator():
        accumulated_text: list[str] = []
        captured_sources: list[dict] = []

        try:
            yield json.dumps({"type": "conversation", "conversation_id": conversation.id}, ensure_ascii=False) + "\n"

            for event in assessor.ask_stream(
                request.question,
                cnpj=request.cnpj,
                statement_type=request.statement_type,
                history=history,
            ):
                if event["type"] == "sources":
                    captured_sources = event["sources"]
                elif event["type"] == "token":
                    accumulated_text.append(event["text"])
                yield json.dumps(event, ensure_ascii=False) + "\n"

            store.add_message(
                conversation.id,
                role="assistant",
                content="".join(accumulated_text),
                sources=captured_sources,
            )
        except Exception as exc:
            logger.exception("Erro durante streaming de chat para conversa %s", conversation.id)
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
