"""
Structure-aware chunking.

Design decision: we chunk WITHIN each RawSegment's boundary, never across
it. A RawSegment is already a structural unit (a page, a slide, a DOCX
section, a sheet row-block) so splitting across segment boundaries would
mean a single chunk could span two different page numbers / two different
slides — which breaks exact citation, the single most heavily weighted
requirement in this system.

Within a segment:
  - If the segment text is short enough (<= MAX_CHUNK_CHARS), it becomes
    ONE chunk as-is. Most slides, table segments, and sheet row-blocks
    fall in this category already.
  - If the segment text is longer (typical for dense PDF/DOCX pages or
    sections), we split on paragraph boundaries first, then pack
    paragraphs into chunks up to MAX_CHUNK_CHARS with CHUNK_OVERLAP_CHARS
    of trailing overlap carried into the next chunk, so a sentence that
    happens to fall on a chunk boundary isn't orphaned from its context.

This is a deliberate trade-off vs. naive fixed-size sliding-window
chunking: it costs more code, but a fixed window would frequently cut
a chunk mid-procedure-step in an SOP document, and unlike fixed windows
it never needs to track "what page/slide does character offset N belong
to" because it never crosses that boundary in the first place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.extractors.base import RawSegment

MAX_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 40  # drop fragments smaller than this (e.g. stray headers)


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source_file: str
    location_type: str
    location_value: str
    extra: dict = field(default_factory=dict)


def _split_into_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


def _pack_paragraphs(paragraphs: list[str]) -> list[str]:
    """Greedily pack paragraphs into chunks <= MAX_CHUNK_CHARS, carrying
    trailing overlap text forward into the next chunk for context
    continuity across the split point.
    """
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n{para}".strip() if current else para

        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
            continue

        # Flush current chunk; start new one with overlap + this paragraph
        if current:
            chunks.append(current)
            overlap = current[-CHUNK_OVERLAP_CHARS:]
            current = f"{overlap}\n{para}".strip()
        else:
            # single paragraph already exceeds max size; hard-split it
            for start in range(0, len(para), MAX_CHUNK_CHARS):
                chunks.append(para[start : start + MAX_CHUNK_CHARS])
            current = ""

        # if even the overlap+para combo is too big, hard split it too
        if len(current) > MAX_CHUNK_CHARS:
            for start in range(0, len(current), MAX_CHUNK_CHARS):
                chunks.append(current[start : start + MAX_CHUNK_CHARS])
            current = ""

    if current:
        chunks.append(current)

    return chunks


def chunk_segment(segment: RawSegment) -> list[Chunk]:
    text = segment.text.strip()
    if len(text) < MIN_CHUNK_CHARS:
        return []

    if len(text) <= MAX_CHUNK_CHARS:
        pieces = [text]
    else:
        paragraphs = _split_into_paragraphs(text)
        pieces = _pack_paragraphs(paragraphs)

    chunks: list[Chunk] = []
    for piece in pieces:
        if len(piece.strip()) < MIN_CHUNK_CHARS:
            continue
        chunks.append(
            Chunk(
                chunk_id=str(uuid.uuid4()),
                text=piece.strip(),
                source_file=segment.source_file,
                location_type=segment.location_type,
                location_value=segment.location_value,
                extra=segment.extra,
            )
        )
    return chunks


def chunk_segments(segments: list[RawSegment]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for segment in segments:
        chunks.extend(chunk_segment(segment))
    return chunks
