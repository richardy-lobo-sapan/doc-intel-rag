"""
Ingestion orchestration. Ties together router -> chunking -> embeddings
-> vectorstore for one file at a time, with simple batch embedding for
efficiency (one model.encode() call per file rather than per-chunk).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.chunking import Chunk, chunk_segments
from app.embeddings import embed_passages
from app.router import extract_document
from app.vectorstore import insert_chunks


@dataclass
class IngestResult:
    file_name: str
    num_segments: int
    num_chunks: int


def ingest_file(file_path: Path) -> IngestResult:
    segments = extract_document(file_path)
    chunks: list[Chunk] = chunk_segments(segments)

    if chunks:
        embeddings = embed_passages([c.text for c in chunks])
        insert_chunks(chunks, embeddings)

    return IngestResult(
        file_name=file_path.name,
        num_segments=len(segments),
        num_chunks=len(chunks),
    )


def ingest_directory(directory: Path) -> list[IngestResult]:
    results = []
    for file_path in sorted(directory.iterdir()):
        if file_path.is_file() and not file_path.name.startswith("."):
            results.append(ingest_file(file_path))
    return results
