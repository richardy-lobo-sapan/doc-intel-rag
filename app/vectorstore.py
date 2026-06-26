"""
Postgres + pgvector backed vector store.

Schema design: a single `chunks` table holds text + embedding + all
citation metadata flattened into columns (not a JSON blob) so that
metadata filtering (e.g. "only search within file X") can use normal
indexed SQL predicates rather than JSON path queries. The `extra` field
from Chunk (headers, table flag, etc.) is the one thing kept as JSONB
since it's genuinely variable-shape per format and not used for filtering.

Index: pgvector's HNSW index (via `vector_cosine_ops`) for approximate
nearest-neighbor search. HNSW over IVFFlat because HNSW doesn't require
a separate training/ANALYZE step that depends on data already being
loaded — convenient for a corpus this size where we ingest once and the
index should just work immediately.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from pgvector.psycopg import register_vector

from app.chunking import Chunk
from app.config import settings

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        UUID PRIMARY KEY,
    text            TEXT NOT NULL,
    source_file     TEXT NOT NULL,
    location_type   TEXT NOT NULL,
    location_value  TEXT NOT NULL,
    extra           JSONB DEFAULT '{{}}',
    embedding       vector({settings.embedding_dim}) NOT NULL
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_source_file_idx
    ON chunks (source_file);
"""


def get_connection() -> psycopg.Connection:
    """Connection for normal use, after the vector extension is known to
    exist (i.e. after init_schema() has run at least once)."""
    conn = psycopg.connect(settings.database_url, autocommit=True)
    register_vector(conn)
    return conn


def init_schema() -> None:
    """Create the vector extension and schema. Uses a raw connection
    (no register_vector) for the FIRST statement, since register_vector
    needs the 'vector' type to already exist in the database -- on a
    fresh database, it doesn't yet. Once the extension is created, the
    rest of the schema can be applied on a normal registered connection.
    """
    with psycopg.connect(settings.database_url, autocommit=True) as raw_conn:
        raw_conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    with get_connection() as conn:
        conn.execute(SCHEMA_SQL)


def insert_chunks(chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must be the same length")

    with get_connection() as conn:
        with conn.cursor() as cur:
            for chunk, embedding in zip(chunks, embeddings):
                cur.execute(
                    """
                    INSERT INTO chunks
                        (chunk_id, text, source_file, location_type, location_value, extra, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO NOTHING
                    """,
                    (
                        chunk.chunk_id,
                        chunk.text,
                        chunk.source_file,
                        chunk.location_type,
                        chunk.location_value,
                        psycopg.types.json.Jsonb(chunk.extra),
                        embedding,
                    ),
                )


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source_file: str
    location_type: str
    location_value: str
    extra: dict
    similarity: float


def similarity_search(
    query_embedding: list[float], top_k: int, source_file: str | None = None
) -> list[RetrievedChunk]:
    """Retrieve the top_k most similar chunks.

    Over-fetches (2x top_k, capped) and deduplicates on
    (source_file, location_value, text) before truncating to top_k. This
    matters because the chunker's overlap strategy can occasionally
    produce two chunks from the same page/slide with substantially
    overlapping or identical text -- without dedup, a single source could
    occupy multiple slots in the result and crowd out genuinely different
    sources, which is exactly the failure mode this system is meant to
    avoid (citations should point to distinct evidence, not repeat
    themselves).
    """
    where_clause = "WHERE source_file = %s" if source_file else ""
    fetch_limit = min(top_k * 2, 50)

    # The query embedding must be explicitly cast to ::vector. Without the
    # cast, psycopg adapts a Python list[float] as a generic array type,
    # and Postgres has no <=> operator between vector and double precision[]
    # -- register_vector() on this connection handles INSERT-side adaptation
    # automatically, but does not change how a bare %s placeholder is typed
    # in a SELECT, so the cast must be explicit here.
    sql = f"""
        SELECT chunk_id, text, source_file, location_type, location_value, extra,
               1 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        {where_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """

    params: list = [query_embedding]
    if source_file:
        params.append(source_file)
    params.append(query_embedding)
    params.append(fetch_limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    seen: set[tuple[str, str, str]] = set()
    deduped: list[RetrievedChunk] = []

    for row in rows:
        text = row[1]
        src_file = row[2]
        location_value = row[4]
        dedup_key = (src_file, location_value, text)

        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        deduped.append(
            RetrievedChunk(
                chunk_id=str(row[0]),
                text=text,
                source_file=src_file,
                location_type=row[3],
                location_value=location_value,
                extra=row[5] or {},
                similarity=float(row[6]),
            )
        )

        if len(deduped) >= top_k:
            break

    return deduped


def count_chunks() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks")
            return cur.fetchone()[0]


def list_indexed_files() -> list[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT source_file FROM chunks ORDER BY source_file")
            return [row[0] for row in cur.fetchall()]
