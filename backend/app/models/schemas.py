"""Schemas Pydantic usados nos endpoints da API (validação + documentação automática)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Pergunta do usuário em linguagem natural")
    cnpj: Optional[str] = Field(None, description="Filtra a busca por uma empresa específica (CNPJ)")
    statement_type: Optional[str] = Field(
        None, description="Filtra por tipo de demonstração, ex: 'Balanço Patrimonial Ativo'"
    )
    conversation_id: Optional[str] = Field(
        None, description="ID de uma conversa existente, para continuar o histórico. Se omitido, cria uma nova."
    )


class SourceItem(BaseModel):
    company_name: Optional[str]
    statement_type: Optional[str]
    period_end: Optional[str]
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    conversation_id: str


class MessageItem(BaseModel):
    role: str
    content: str
    sources: Optional[list] = None
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    message_count: int


class ConversationDetail(BaseModel):
    id: str
    created_at: datetime
    messages: list[MessageItem]


# ── Autenticação ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Mínimo 8 caracteres")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: datetime
