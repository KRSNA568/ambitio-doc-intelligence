"""Tests for the sliding-window chunker (overlap is what keeps facts
retrievable across boundaries)."""

import retriever


def test_short_text_single_chunk():
    chunks = retriever._chunk_text("just a few words here")
    assert len(chunks) == 1
    assert chunks[0] == "just a few words here"


def test_empty_text_no_chunks():
    assert retriever._chunk_text("") == []
    assert retriever._chunk_text("   ") == []


def test_long_text_multiple_overlapping_chunks():
    # 700 words -> with size 300 / step 250 we expect 3 chunks.
    words = [f"w{i}" for i in range(700)]
    chunks = retriever._chunk_text(" ".join(words))
    assert len(chunks) == 3
    # Each chunk is at most CHUNK_SIZE_TOKENS words.
    for c in chunks:
        assert len(c.split()) <= retriever.CHUNK_SIZE_TOKENS


def test_overlap_between_consecutive_chunks():
    words = [f"w{i}" for i in range(700)]
    chunks = retriever._chunk_text(" ".join(words))
    first_tail = chunks[0].split()[-retriever.CHUNK_OVERLAP_TOKENS:]
    second_head = chunks[1].split()[: retriever.CHUNK_OVERLAP_TOKENS]
    # The overlap region must be shared verbatim.
    assert first_tail == second_head


def test_page_number_distribution():
    # Chunks should map monotonically across the page range.
    assert retriever._approx_page_number(0, 4, 2) == 1
    assert retriever._approx_page_number(3, 4, 2) == 2
    # Degenerate inputs fall back to page 1.
    assert retriever._approx_page_number(0, 0, 0) == 1
