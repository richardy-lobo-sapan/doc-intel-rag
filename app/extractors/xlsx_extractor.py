"""
XLSX extraction via openpyxl.

Granularity: one RawSegment per sheet, with rows grouped into blocks of
ROW_BLOCK_SIZE so a single segment doesn't balloon on very large sheets.
Each row is rendered as "col_header: value | col_header: value" using the
first row as headers, which gives the embedding model column-aware
context (e.g. "Audit Item: Fire extinguisher | Status: Compliant") rather
than a bare comma-separated row that loses column meaning.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

from app.extractors.base import BaseExtractor, RawSegment

ROW_BLOCK_SIZE = 25


class XLSXExtractor(BaseExtractor):
    supported_extensions = (".xlsx",)

    def extract(self, file_path: Path) -> list[RawSegment]:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        segments: list[RawSegment] = []

        for sheet in wb.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue

            headers = [str(h) if h is not None else "" for h in rows[0]]
            data_rows = rows[1:]
            if not data_rows:
                continue

            for block_start in range(0, len(data_rows), ROW_BLOCK_SIZE):
                block = data_rows[block_start : block_start + ROW_BLOCK_SIZE]
                line_texts = []
                for row in block:
                    pairs = [
                        f"{headers[i]}: {row[i]}"
                        for i in range(min(len(headers), len(row)))
                        if row[i] is not None
                    ]
                    if pairs:
                        line_texts.append(" | ".join(pairs))

                if not line_texts:
                    continue

                first_row_num = block_start + 2  # +1 header, +1 for 1-indexing
                last_row_num = first_row_num + len(block) - 1

                segments.append(
                    RawSegment(
                        text="\n".join(line_texts),
                        source_file=file_path.name,
                        location_type="sheet",
                        location_value=sheet.title,
                        extra={
                            "row_range": f"{first_row_num}-{last_row_num}",
                            "headers": headers,
                        },
                    )
                )

        return segments
