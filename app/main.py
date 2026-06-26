from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.ingest import router as ingest_router
from app.api.query import router as query_router
from app.vectorstore import init_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()
    yield


app = FastAPI(
    title="Document Intelligence RAG API",
    description=(
        "Multi-format document ingestion and retrieval-augmented "
        "question answering with traceable source citations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(ingest_router, tags=["ingestion"])
app.include_router(query_router, tags=["query"])


@app.get("/health")
async def health():
    return {"status": "ok"}
