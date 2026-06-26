"""
Unit tests for the extraction layer. These run against the generated
sample corpus in data/corpus and require no database or network access,
so they're safe to run in CI.
"""

from pathlib import Path

import pytest

from app.router import extract_document, get_extractor_for, UnsupportedFormatError
from app.chunking import chunk_segments

CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "corpus"


def _corpus_files():
    if not CORPUS_DIR.exists():
        return []
    return sorted(p for p in CORPUS_DIR.iterdir() if p.is_file())


@pytest.mark.parametrize("file_path", _corpus_files(), ids=lambda p: p.name)
def test_extract_produces_segments_with_required_fields(file_path):
    segments = extract_document(file_path)
    assert len(segments) > 0, f"No segments extracted from {file_path.name}"

    for seg in segments:
        assert seg.text.strip(), "segment text must not be empty"
        assert seg.source_file == file_path.name
        assert seg.location_type in {"page", "slide", "sheet", "row_range", "section"}
        assert seg.location_value, "location_value must not be empty"


@pytest.mark.parametrize("file_path", _corpus_files(), ids=lambda p: p.name)
def test_chunking_preserves_location_metadata(file_path):
    segments = extract_document(file_path)
    chunks = chunk_segments(segments)

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.source_file == file_path.name
        assert chunk.text.strip()
        assert chunk.chunk_id


def test_unsupported_format_raises(tmp_path):
    bogus_file = tmp_path / "notes.xyz"
    bogus_file.write_text("hello")
    with pytest.raises(UnsupportedFormatError):
        get_extractor_for(bogus_file)


def test_mislabeled_office_file_raises(tmp_path):
    # A .docx extension on a file that isn't actually a valid zip/OOXML doc
    fake_docx = tmp_path / "fake.docx"
    fake_docx.write_text("this is not a real docx file")
    with pytest.raises(UnsupportedFormatError):
        get_extractor_for(fake_docx)
