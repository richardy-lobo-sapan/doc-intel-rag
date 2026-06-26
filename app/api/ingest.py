from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from app.ingestion import ingest_file
from app.router import UnsupportedFormatError
from app.vectorstore import count_chunks, list_indexed_files

router = APIRouter()


@router.post("/ingest")
async def ingest_endpoint(file: UploadFile):
    tmp_dir = Path(tempfile.mkdtemp())
    # Use the original filename (not a random tmp name) so extractors and
    # citations report the real document name to the user.
    tmp_path = tmp_dir / file.filename

    with open(tmp_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        result = ingest_file(tmp_path)
    except UnsupportedFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "file_name": result.file_name,
        "segments_extracted": result.num_segments,
        "chunks_indexed": result.num_chunks,
    }


@router.get("/documents")
async def list_documents():
    return {"indexed_files": list_indexed_files(), "total_chunks": count_chunks()}
