from app.extractors.base import BaseExtractor, RawSegment
from app.extractors.csv_txt_extractor import CSVExtractor, TXTExtractor
from app.extractors.docx_extractor import DOCXExtractor
from app.extractors.pdf_extractor import PDFExtractor
from app.extractors.pptx_extractor import PPTXExtractor
from app.extractors.xlsx_extractor import XLSXExtractor

ALL_EXTRACTORS: list[type[BaseExtractor]] = [
    PDFExtractor,
    DOCXExtractor,
    PPTXExtractor,
    XLSXExtractor,
    CSVExtractor,
    TXTExtractor,
]

__all__ = [
    "BaseExtractor",
    "RawSegment",
    "PDFExtractor",
    "DOCXExtractor",
    "PPTXExtractor",
    "XLSXExtractor",
    "CSVExtractor",
    "TXTExtractor",
    "ALL_EXTRACTORS",
]
