from app.chunking import MAX_CHUNK_CHARS, MIN_CHUNK_CHARS, chunk_segment
from app.extractors.base import RawSegment


def test_short_segment_becomes_single_chunk():
    segment = RawSegment(
        text="This is a short paragraph about an audit procedure.",
        source_file="test.pdf",
        location_type="page",
        location_value="1",
    )
    chunks = chunk_segment(segment)
    assert len(chunks) == 1
    assert chunks[0].text == segment.text
    assert chunks[0].location_value == "1"


def test_long_segment_is_split_but_stays_under_max_chars():
    long_text = "\n".join([f"Paragraph number {i} with some filler content." for i in range(200)])
    segment = RawSegment(
        text=long_text,
        source_file="test.pdf",
        location_type="page",
        location_value="5",
    )
    chunks = chunk_segment(segment)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS + 50  # small tolerance for overlap join
        # every chunk from this segment must still carry the original page number
        assert chunk.location_value == "5"
        assert chunk.location_type == "page"


def test_tiny_fragment_is_dropped():
    segment = RawSegment(
        text="Hi",
        source_file="test.pdf",
        location_type="page",
        location_value="1",
    )
    chunks = chunk_segment(segment)
    assert chunks == []


def test_chunk_never_crosses_segment_boundary():
    # Two segments representing two different pages should never merge
    # into a single chunk, even if both are short.
    seg1 = RawSegment(
        text="A" * (MIN_CHUNK_CHARS + 10),
        source_file="test.pdf",
        location_type="page",
        location_value="1",
    )
    seg2 = RawSegment(
        text="B" * (MIN_CHUNK_CHARS + 10),
        source_file="test.pdf",
        location_type="page",
        location_value="2",
    )
    chunks1 = chunk_segment(seg1)
    chunks2 = chunk_segment(seg2)
    all_chunks = chunks1 + chunks2

    page_1_chunks = [c for c in all_chunks if c.location_value == "1"]
    page_2_chunks = [c for c in all_chunks if c.location_value == "2"]

    assert all("A" in c.text and "B" not in c.text for c in page_1_chunks)
    assert all("B" in c.text and "A" not in c.text for c in page_2_chunks)
