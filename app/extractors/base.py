"""
Base interface that every format-specific extractor implements.

Design decision: extractors do NOT chunk text themselves. They only produce
"RawSegment" objects — the smallest structurally meaningful unit for that
format (a paragraph, a slide, a sheet row-block, a CSV row-group). The
chunker (app/chunking.py) is responsible for merging/splitting these into
final chunks. This keeps format-specific logic (page numbers, slide
indices, sheet names) separate from chunking strategy, so we can change
chunking without touching extractors and vice versa.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RawSegment:
    """A structurally meaningful piece of text extracted from a source file,
    tagged with enough metadata to trace it back to an exact location.
    """

    text: str
    source_file: str  # original filename, e.g. "sop_quality_audit.pdf"
    location_type: str  # "page" | "slide" | "sheet" | "row_range" | "section"
    location_value: str  # e.g. "3" (page 3), "Sheet1", "rows 12-20"
    extra: dict = field(default_factory=dict)  # heading path, slide title, etc.


class BaseExtractor(ABC):
    """All format extractors implement extract() -> list[RawSegment]."""

    supported_extensions: tuple[str, ...] = ()

    @abstractmethod
    def extract(self, file_path: Path) -> list[RawSegment]:
        raise NotImplementedError

    @classmethod
    def can_handle(cls, file_path: Path) -> bool:
        return file_path.suffix.lower() in cls.supported_extensions
