from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.rag_pipeline import answer_question

router = APIRouter()


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    source_file: str | None = None


class SourceResponse(BaseModel):
    label: str
    source_file: str
    location_type: str
    location_value: str
    similarity: float
    excerpt: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest):
    result = answer_question(
        question=request.question,
        top_k=request.top_k,
        source_file=request.source_file,
    )
    return QueryResponse(
        answer=result.answer,
        sources=[SourceResponse(**vars(s)) for s in result.sources],
    )
