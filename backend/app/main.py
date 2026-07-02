"""
Aplicação FastAPI principal do InvestAI.

Roda com:
    uvicorn backend.app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.db import Base, engine
from backend.app.routers import auth, chat, conversations


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="InvestAI — Assessor de Investimentos",
    description=(
        "API RAG que responde perguntas com base em demonstrações financeiras "
        "abertas da CVM, sempre citando as fontes utilizadas."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(conversations.router)


@app.get("/health", tags=["infra"])
def health() -> dict:
    return {"status": "ok"}
