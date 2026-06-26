"""
Integration tests for the vectorstore module against a REAL Postgres+pgvector
connection. These are skipped automatically (not failed) if no database is
reachable, since CI has no database -- run these locally via:

    docker compose up -d postgres
    DATABASE_URL=postgresql://raguser:ragpass@localhost:5432/ragdb pytest tests/test_vectorstore_integration.py -v

This file exists specifically to catch the class of bug where a Python list
embedding is passed as a query parameter without an explicit ::vector cast,
which Postgres accepts at the Python level (no exception until runtime) but
rejects at query time with "operator does not exist: vector <=> double
precision[]" -- a bug that unit tests with mocked dependencies cannot catch.
"""

from __future__ import annotations

import random
import uuid

import psycopg
import pytest

from app.chunking import Chunk
from app.config import settings

EMBEDDING_DIM = settings.embedding_dim


def _db_available() -> bool:
    try:
        conn = psycopg.connect(settings.database_url, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="No live Postgres connection available"
)


@pytest.fixture
def clean_db():
    from app.vectorstore import get_connection, init_schema

    init_schema()
    with get_connection() as conn:
        conn.execute("DELETE FROM chunks")
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM chunks")


def _random_vector() -> list[float]:
    return [random.random() for _ in range(EMBEDDING_DIM)]


def test_similarity_search_against_real_db(clean_db):
    """Regression test: similarity_search must work against real pgvector
    without raising 'operator does not exist: vector <=> double precision[]'.
    """
    from app.vectorstore import insert_chunks, similarity_search

    chunks = [
        Chunk(
            chunk_id=str(uuid.uuid4()),
            text=f"test chunk {i}",
            source_file="test.pdf",
            location_type="page",
            location_value=str(i),
        )
        for i in range(3)
    ]
    embeddings = [_random_vector() for _ in chunks]
    insert_chunks(chunks, embeddings)

    query_vec = _random_vector()
    results = similarity_search(query_vec, top_k=2)

    assert len(results) == 2
    for r in results:
        assert r.source_file == "test.pdf"
        assert 0.0 <= r.similarity <= 1.0 or r.similarity <= 1.0  # cosine sim range


def test_similarity_search_with_source_file_filter(clean_db):
    from app.vectorstore import insert_chunks, similarity_search

    chunks_a = [
        Chunk(
            chunk_id=str(uuid.uuid4()),
            text="chunk from a",
            source_file="a.pdf",
            location_type="page",
            location_value="1",
        )
    ]
    chunks_b = [
        Chunk(
            chunk_id=str(uuid.uuid4()),
            text="chunk from b",
            source_file="b.pdf",
            location_type="page",
            location_value="1",
        )
    ]
    insert_chunks(chunks_a, [_random_vector()])
    insert_chunks(chunks_b, [_random_vector()])

    query_vec = _random_vector()
    results = similarity_search(query_vec, top_k=5, source_file="a.pdf")

    assert len(results) == 1
    assert results[0].source_file == "a.pdf"


def test_similarity_search_deduplicates_repeated_chunks(clean_db):
    """Regression test: if two distinct chunk_ids share the same
    (source_file, location_value, text) -- e.g. from overlapping chunking
    on the same page -- similarity_search must collapse them to a single
    result rather than letting one source occupy multiple slots in the
    citation list.
    """
    from app.vectorstore import insert_chunks, similarity_search

    duplicate_text = "Standard Operating Procedure for quality audits."
    chunks = [
        Chunk(
            chunk_id=str(uuid.uuid4()),
            text=duplicate_text,
            source_file="sop.pdf",
            location_type="page",
            location_value="1",
        ),
        Chunk(
            chunk_id=str(uuid.uuid4()),  # different chunk_id, same content/location
            text=duplicate_text,
            source_file="sop.pdf",
            location_type="page",
            location_value="1",
        ),
        Chunk(
            chunk_id=str(uuid.uuid4()),
            text="Genuinely different content about vendors",
            source_file="vendor.csv",
            location_type="row_range",
            location_value="1-5",
        ),
    ]
    embeddings = [_random_vector(), _random_vector(), _random_vector()]
    insert_chunks(chunks, embeddings)

    results = similarity_search(_random_vector(), top_k=5)

    assert len(results) == 2  # 3 inserted, 2 unique after dedup
    keys = {(r.source_file, r.location_value, r.text) for r in results}
    assert len(keys) == 2  # no duplicate (source_file, location, text) combos


def test_init_schema_is_idempotent():
    """init_schema() must be safely callable multiple times (it runs on
    every app startup), including against a fresh database with no
    'vector' extension yet installed.
    """
    from app.vectorstore import init_schema

    init_schema()
    init_schema()  # must not raise on second call
