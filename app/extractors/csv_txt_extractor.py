"""
CSV/TXT extraction.

CSV uses the same column-aware row-block approach as XLSX (via pandas)
so citation granularity is consistent across tabular formats. TXT files
are split into fixed-size character blocks since there's no structural
metadata available at all in a plain text file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.extractors.base import BaseExtractor, RawSegment

ROW_BLOCK_SIZE = 25
TXT_BLOCK_CHARS = 2000


class CSVExtractor(BaseExtractor):
    supported_extensions = (".csv",)

    def extract(self, file_path: Path) -> list[RawSegment]:
        df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        segments: list[RawSegment] = []
        headers = list(df.columns)

        for block_start in range(0, len(df), ROW_BLOCK_SIZE):
            block = df.iloc[block_start : block_start + ROW_BLOCK_SIZE]
            line_texts = []
            for _, row in block.iterrows():
                pairs = [f"{h}: {row[h]}" for h in headers if str(row[h]).strip()]
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
                    location_type="row_range",
                    location_value=f"{first_row_num}-{last_row_num}",
                    extra={"headers": headers},
                )
            )

        return segments


class TXTExtractor(BaseExtractor):
    supported_extensions = (".txt",)

    def extract(self, file_path: Path) -> list[RawSegment]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        segments: list[RawSegment] = []

        for block_index, start in enumerate(range(0, len(text), TXT_BLOCK_CHARS), start=1):
            block_text = text[start : start + TXT_BLOCK_CHARS].strip()
            if block_text:
                segments.append(
                    RawSegment(
                        text=block_text,
                        source_file=file_path.name,
                        location_type="section",
                        location_value=f"block {block_index}",
                    )
                )

        return segments
