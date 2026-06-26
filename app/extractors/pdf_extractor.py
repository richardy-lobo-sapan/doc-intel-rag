"""
PDF extraction via PyMuPDF (fitz).

Why PyMuPDF over pdfplumber: faster on large batches, gives reliable
per-page text blocks, and handles most "born-digital" PDFs (the kind
internal SOPs/regulations usually are) without needing OCR. We do NOT
attempt OCR for scanned/image-only PDFs in this version — see
TECHNICAL.md trade-offs section for why, and what a Phase 2 addition
(Tesseract/EasyOCR fallback) would look like.

Granularity: one RawSegment per page. A page is small enough to be a
sensible chunking unit and large enough to avoid producing hundreds of
tiny fragments per document.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from app.extractors.base import BaseExtractor, RawSegment


class PDFExtractor(BaseExtractor):
    supported_extensions = (".pdf",)

    def extract(self, file_path: Path) -> list[RawSegment]:
        segments: list[RawSegment] = []
        doc = fitz.open(file_path)
        try:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                text = page.get_text("text").strip()
                if not text:
                    continue  # skip blank pages (e.g. section dividers)
                segments.append(
                    RawSegment(
                        text=text,
                        source_file=file_path.name,
                        location_type="page",
                        location_value=str(page_index + 1),
                        extra={"total_pages": doc.page_count},
                    )
                )
        finally:
            doc.close()
        return segments
