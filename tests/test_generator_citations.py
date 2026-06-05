"""Tests for citation handling — the traceability guarantee that every draft
sentence maps back to a source chunk_id."""

import generator
from models import RetrievedChunk


def _chunks():
    return [
        RetrievedChunk(chunk_id="doc::chunk::0", doc_id="doc", chunk_index=0,
                       page_number=1, text="Agreement signed Jan 15 2021.", score=0.9),
        RetrievedChunk(chunk_id="doc::chunk::1", doc_id="doc", chunk_index=1,
                       page_number=1, text="Dispute began March 2021.", score=0.8),
    ]


def test_format_evidence_labels_map_to_chunk_ids():
    text, label_map = generator._format_evidence(_chunks())
    assert "[E1]" in text and "[E2]" in text
    assert label_map == {"E1": "doc::chunk::0", "E2": "doc::chunk::1"}


def test_parse_response_extracts_draft_and_citations():
    label_map = {"E1": "doc::chunk::0", "E2": "doc::chunk::1"}
    raw = (
        "<draft>\nThe agreement was signed [E1]. The dispute began later [E2].\n</draft>\n"
        '<citations>\n{"s1": ["E1"], "s2": ["E2"]}\n</citations>'
    )
    draft, citations = generator._parse_response(raw, label_map)
    assert "agreement was signed" in draft
    # Labels must be translated to stable chunk_ids.
    assert citations == {"s1": ["doc::chunk::0"], "s2": ["doc::chunk::1"]}


def test_parse_response_falls_back_to_markers_without_citation_block():
    label_map = {"E1": "doc::chunk::0", "E2": "doc::chunk::1"}
    raw = "<draft>First fact [E1]. Second fact [E2].</draft>"
    draft, citations = generator._parse_response(raw, label_map)
    # Derived from inline [E#] markers when no JSON block is present.
    assert citations["s1"] == ["doc::chunk::0"]
    assert citations["s2"] == ["doc::chunk::1"]


def test_every_sentence_with_marker_is_traced():
    label_map = {"E1": "doc::chunk::0"}
    draft = "Alpha happened [E1]. Beta happened [E1]."
    citations = generator._citations_from_markers(draft, label_map)
    assert all(cids == ["doc::chunk::0"] for cids in citations.values())
    assert len(citations) == 2
