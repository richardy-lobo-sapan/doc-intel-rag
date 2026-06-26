"""
Batch-ingest every file in data/corpus into the vector store.

Usage:
    python scripts/ingest_corpus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion import ingest_directory  # noqa: E402
from app.vectorstore import init_schema  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "corpus"


def main() -> None:
    print("Initializing database schema...")
    init_schema()

    print(f"Ingesting documents from {CORPUS_DIR}...")
    results = ingest_directory(CORPUS_DIR)

    total_chunks = 0
    for result in results:
        print(
            f"  {result.file_name}: {result.num_segments} segments -> "
            f"{result.num_chunks} chunks"
        )
        total_chunks += result.num_chunks

    print(f"\nDone. {len(results)} files ingested, {total_chunks} chunks indexed.")


if __name__ == "__main__":
    main()
