"""
generator.py
------------
Grounded draft generation.

Given the structured fields, a set of retrieved evidence chunks, and any
operator rules learned from past edits, produce a Case Fact Summary in which
*every* claim is tied to an evidence block via inline [E#] citations.

Design choices
==============
- Evidence is injected as numbered blocks [E1]..[Ek]. The model is told to cite
  the block(s) that support each sentence and is explicitly forbidden from
  asserting anything not present in the evidence. This is the core
  anti-hallucination mechanism.
- We ask the model to additionally return a machine-readable citation map
  (sentence -> [E#]) inside a JSON block, which we translate from [E#] labels
  back to stable chunk_ids so the frontend can trace each sentence to source.
- Operator rules (natural-language preferences mined by learner.py) are
  injected verbatim so the draft visibly adapts to operator style.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Tuple

import llm
from models import EvidenceBlock, GenerateResponse, RetrievedChunk, StructuredFields


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
_BASE_SYSTEM_PROMPT = """You are a meticulous legal drafting assistant. Your job \
is to write a concise **Case Fact Summary** that an operator will review.

You will be given:
1. Structured fields already extracted from the document.
2. Numbered EVIDENCE blocks labelled [E1], [E2], ... — these are verbatim
   excerpts from the source document.
3. Optionally, OPERATOR RULES describing how this operator likes summaries
   written. Follow them.

HARD REQUIREMENTS — these are non-negotiable:
- Ground EVERY factual sentence in the evidence. After each sentence, cite the
  supporting block(s) inline, e.g.: "The dispute began in March 2021 [E2]."
- A sentence may cite multiple blocks: "... [E1][E3]".
- Do NOT assert any fact that is not supported by an evidence block. If the
  evidence is silent on something, omit it — never guess or use outside
  knowledge.
- Prefer the operator's preferred structure/tone if OPERATOR RULES are given.

OUTPUT FORMAT — return exactly two parts, in this order:

<draft>
...the Case Fact Summary text, with inline [E#] citations...
</draft>

<citations>
{ "s1": ["E2"], "s2": ["E1", "E3"], ... }
</citations>

In the citations JSON, number sentences s1, s2, ... in the order they appear in
the draft, mapping each to the list of evidence labels it cites.
"""


def _format_structured(fields: StructuredFields) -> str:
    return (
        "STRUCTURED FIELDS (for context; still cite evidence for any claim you make):\n"
        f"- case_number: {fields.case_number}\n"
        f"- parties: {fields.parties}\n"
        f"- dates: {fields.dates}\n"
        f"- document_type: {fields.document_type}\n"
        f"- key_facts: {fields.key_facts}\n"
    )


def _format_evidence(chunks: List[RetrievedChunk]) -> Tuple[str, Dict[str, str]]:
    """
    Render evidence blocks and return (text, label->chunk_id map).
    label is "E1", "E2", ...
    """
    lines = ["EVIDENCE BLOCKS:"]
    label_to_chunk: Dict[str, str] = {}
    for i, c in enumerate(chunks, start=1):
        label = f"E{i}"
        label_to_chunk[label] = c.chunk_id
        lines.append(f"[{label}] (page {c.page_number}, score {c.score})\n{c.text}\n")
    return "\n".join(lines), label_to_chunk


def _format_rules(rules: List[str]) -> str:
    if not rules:
        return ""
    bullet = "\n".join(f"- {r}" for r in rules)
    return f"\nOPERATOR RULES (apply these to your draft):\n{bullet}\n"


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #
def _parse_response(text: str, label_to_chunk: Dict[str, str]) -> Tuple[str, Dict[str, List[str]]]:
    """Pull the <draft> and <citations> sections out of the model output."""
    draft_match = re.search(r"<draft>(.*?)</draft>", text, re.DOTALL)
    cite_match = re.search(r"<citations>(.*?)</citations>", text, re.DOTALL)

    draft = draft_match.group(1).strip() if draft_match else text.strip()

    citations: Dict[str, List[str]] = {}
    if cite_match:
        try:
            raw_map = json.loads(cite_match.group(1).strip())
            # Translate evidence labels -> stable chunk_ids.
            for sentence_id, labels in raw_map.items():
                citations[sentence_id] = [
                    label_to_chunk.get(lbl, lbl) for lbl in labels
                ]
        except json.JSONDecodeError:
            citations = {}

    # Fallback: if the model gave no citation map, derive one by scanning the
    # draft for [E#] markers per sentence so the frontend still gets traces.
    if not citations:
        citations = _citations_from_markers(draft, label_to_chunk)

    return draft, citations


def _citations_from_markers(
    draft: str, label_to_chunk: Dict[str, str]
) -> Dict[str, List[str]]:
    """Best-effort: split into sentences and map any [E#] markers found."""
    sentences = re.split(r"(?<=[.!?])\s+", draft)
    out: Dict[str, List[str]] = {}
    for i, sent in enumerate(sentences, start=1):
        labels = re.findall(r"\[(E\d+)\]", sent)
        if labels:
            out[f"s{i}"] = [label_to_chunk.get(lbl, lbl) for lbl in labels]
    return out


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def generate_draft(
    doc_id: str,
    structured_fields: StructuredFields,
    retrieved_chunks: List[RetrievedChunk],
    operator_rules: List[str] | None = None,
) -> GenerateResponse:
    """Produce a grounded Case Fact Summary with citation traces."""
    operator_rules = operator_rules or []

    evidence_text, label_to_chunk = _format_evidence(retrieved_chunks)
    user_content = (
        _format_structured(structured_fields)
        + "\n"
        + evidence_text
        + _format_rules(operator_rules)
        + "\nNow write the Case Fact Summary following all requirements."
    )

    try:
        raw = llm.generate_text(
            system=_BASE_SYSTEM_PROMPT,
            user=user_content,
            max_tokens=1500,
        )
        draft_text, citations = _parse_response(raw, label_to_chunk)
    except Exception as exc:  # noqa: BLE001
        # Surface the failure as a visible draft rather than 500-ing the route.
        draft_text = f"[GENERATION_ERROR: {exc}]"
        citations = {}

    evidence_blocks = [
        EvidenceBlock(
            label=f"E{i}",
            chunk_id=c.chunk_id,
            page_number=c.page_number,
            text=c.text,
            score=c.score,
        )
        for i, c in enumerate(retrieved_chunks, start=1)
    ]

    return GenerateResponse(
        doc_id=doc_id,
        draft_text=draft_text,
        citations=citations,
        evidence=evidence_blocks,
        applied_rules=operator_rules,
    )
