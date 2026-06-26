"""
RAG pipeline: retrieve -> prompt -> generate -> structured citations.

Citation design decision: we do NOT rely on the LLM to faithfully report
which source it used in free text. LLMs paraphrase and hallucinate
citations under that approach. Instead:
  1. We retrieve top-k chunks, each with EXACT metadata already known
     (file, page/slide/sheet) before the LLM ever sees them.
  2. We label each chunk [S1], [S2], ... in the prompt and instruct the
     model to reference labels inline in its answer.
  3. The API response always returns the full source list with real
     metadata regardless of which labels the model chose to mention, so
     citation correctness never depends on the LLM "getting it right" in
     free text -- worst case, the model's inline labels are imperfect but
     the source list is always grounded and accurate.

Observability: retrieval and generation are each wrapped in a Langfuse
observation (v3 OpenTelemetry-based SDK) when LANGFUSE_PUBLIC_KEY /
LANGFUSE_SECRET_KEY are configured. This is intentionally a no-op (not
an error) when those env vars are absent, so the pipeline works exactly
the same with or without observability configured -- tracing is purely
additive, never a hard dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from groq import Groq

from app.config import settings
from app.embeddings import embed_query
from app.vectorstore import RetrievedChunk, similarity_search

_LANGFUSE_ENABLED = bool(settings.langfuse_public_key and settings.langfuse_secret_key)

if _LANGFUSE_ENABLED:
    import os

    # The langfuse client reads credentials from env vars at import/init time.
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)

    from langfuse import get_client

    _langfuse = get_client()
else:
    _langfuse = None

SYSTEM_PROMPT = """You are a document intelligence assistant. Answer the user's \
question using ONLY the numbered source excerpts provided below. Every claim in \
your answer must be traceable to a source.

Rules:
- Cite sources inline using their label, e.g. [S1], [S2].
- If multiple sources support a claim, cite all of them, e.g. [S1][S3].
- If the provided sources do not contain enough information to answer, say so \
explicitly rather than guessing or using outside knowledge.
- Be concise and direct. Do not repeat the question back.
"""


@dataclass
class SourceCitation:
    label: str
    source_file: str
    location_type: str
    location_value: str
    similarity: float
    excerpt: str


@dataclass
class RAGAnswer:
    answer: str
    sources: list[SourceCitation]


def _format_location(chunk: RetrievedChunk) -> str:
    label_map = {
        "page": "page",
        "slide": "slide",
        "sheet": "sheet",
        "section": "section",
        "row_range": "rows",
    }
    label = label_map.get(chunk.location_type, chunk.location_type)
    return f"{label} {chunk.location_value}"


def _build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for i, chunk in enumerate(chunks, start=1):
        location = _format_location(chunk)
        blocks.append(f"[S{i}] (source: {chunk.source_file}, {location})\n{chunk.text}")
    sources_block = "\n\n".join(blocks)
    return f"Sources:\n\n{sources_block}\n\nQuestion: {question}"


def answer_question(
    question: str, top_k: int | None = None, source_file: str | None = None
) -> RAGAnswer:
    if not _LANGFUSE_ENABLED:
        return _answer_question_impl(question, top_k, source_file)

    with _langfuse.start_as_current_observation(
        as_type="span",
        name="rag-query",
        input={"question": question, "top_k": top_k, "source_file": source_file},
    ) as root_span:
        result = _answer_question_impl(question, top_k, source_file)
        root_span.update(
            output={
                "answer": result.answer,
                "num_sources": len(result.sources),
            }
        )
        return result


def _answer_question_impl(
    question: str, top_k: int | None, source_file: str | None
) -> RAGAnswer:
    k = top_k or settings.top_k

    if _LANGFUSE_ENABLED:
        with _langfuse.start_as_current_observation(
            as_type="span", name="retrieval", input={"question": question, "top_k": k}
        ) as retrieval_span:
            query_vec = embed_query(question)
            retrieved = similarity_search(query_vec, top_k=k, source_file=source_file)
            retrieval_span.update(
                output={
                    "num_chunks": len(retrieved),
                    "sources": [
                        f"{c.source_file} ({c.location_type} {c.location_value})"
                        for c in retrieved
                    ],
                }
            )
    else:
        query_vec = embed_query(question)
        retrieved = similarity_search(query_vec, top_k=k, source_file=source_file)

    if not retrieved:
        return RAGAnswer(
            answer="No indexed documents matched this question. Try ingesting "
            "documents first or rephrasing the question.",
            sources=[],
        )

    prompt = _build_prompt(question, retrieved)

    if _LANGFUSE_ENABLED:
        with _langfuse.start_as_current_observation(
            as_type="generation",
            name="groq-generation",
            model=settings.groq_model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        ) as generation_span:
            answer_text = _call_groq(prompt)
            generation_span.update(output=answer_text)
    else:
        answer_text = _call_groq(prompt)

    sources = [
        SourceCitation(
            label=f"S{i}",
            source_file=chunk.source_file,
            location_type=chunk.location_type,
            location_value=chunk.location_value,
            similarity=round(chunk.similarity, 4),
            excerpt=chunk.text[:300],
        )
        for i, chunk in enumerate(retrieved, start=1)
    ]

    return RAGAnswer(answer=answer_text, sources=sources)


def _call_groq(prompt: str) -> str:
    client = Groq(api_key=settings.groq_api_key)
    completion = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    return completion.choices[0].message.content
