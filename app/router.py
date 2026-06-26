"""
Format detection + routing.

Detection strategy: primarily by file extension, since the source corpus
is controlled (internal documents uploaded by a known process) rather than
arbitrary user uploads from the open internet. As a safety net we also
double check the extension against the file's actual magic bytes for the
zip-based Office formats (docx/pptx/xlsx are all zip containers; a
mislabeled .docx that is secretly a .pptx would fail downstream with a
confusing python-docx error rather than a clear "unsupported format" one).
Plain text-based formats (csv/txt) are trusted on extension alone, since
there's no reliable magic-byte signature for them.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.extractors import ALL_EXTRACTORS, RawSegment
from app.extractors.base import BaseExtractor

_OFFICE_ZIP_EXTENSIONS = {".docx", ".pptx", ".xlsx"}

# Identifying internal path inside the OOXML zip that distinguishes the
# three Office formats from each other (and from a generic/corrupt zip).
_OOXML_SIGNATURE_PATH = {
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml",
    ".xlsx": "xl/workbook.xml",
}


class UnsupportedFormatError(Exception):
    pass


def _verify_ooxml_signature(file_path: Path) -> None:
    """Raise if a .docx/.pptx/.xlsx file's internal structure doesn't match
    its extension. Lets us fail with a clear error instead of a confusing
    stack trace deep inside python-docx/python-pptx/openpyxl.
    """
    expected_path = _OOXML_SIGNATURE_PATH[file_path.suffix.lower()]
    try:
        with zipfile.ZipFile(file_path) as zf:
            namelist = zf.namelist()
    except zipfile.BadZipFile:
        raise UnsupportedFormatError(
            f"{file_path.name} has a {file_path.suffix} extension but is not "
            "a valid Office Open XML (zip) file."
        )
    if expected_path not in namelist:
        raise UnsupportedFormatError(
            f"{file_path.name} has a {file_path.suffix} extension but its "
            f"internal structure doesn't match (missing {expected_path}). "
            "The file may be mislabeled."
        )


def get_extractor_for(file_path: Path) -> BaseExtractor:
    suffix = file_path.suffix.lower()

    if suffix in _OFFICE_ZIP_EXTENSIONS:
        _verify_ooxml_signature(file_path)

    for extractor_cls in ALL_EXTRACTORS:
        if extractor_cls.can_handle(file_path):
            return extractor_cls()

    supported = sorted({ext for cls in ALL_EXTRACTORS for ext in cls.supported_extensions})
    raise UnsupportedFormatError(
        f"No extractor available for '{suffix}'. Supported formats: {supported}"
    )


def extract_document(file_path: Path) -> list[RawSegment]:
    """Detect format and extract raw segments from a single file."""
    extractor = get_extractor_for(file_path)
    return extractor.extract(file_path)
