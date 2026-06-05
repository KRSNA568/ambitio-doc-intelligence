"""
eval.py
-------
Groundedness evaluation for generated drafts.

Question we answer: is every sentence in a draft actually supported by the
retrieved source chunks, or is the model drifting into unsupported claims?

Method
======
For each draft sentence we compute the maximum ROUGE-L F1 between that sentence
and any source chunk. ROUGE-L rewards the longest common subsequence, so a
sentence that paraphrases real evidence scores high, while an invented sentence
that shares no phrasing with any chunk scores near zero.

Metrics printed
---------------
- average groundedness  (mean of per-sentence max ROUGE-L)
- unsupported sentences (count + list where max ROUGE-L < THRESHOLD)
- a before/after comparison: the raw AI draft vs the operator-edited draft,
  showing whether edits kept (or improved) grounding.

Usage
-----
    python eval/eval.py
    python eval/eval.py --draft path/to/draft.json --edited path/to/edited.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import List

from rouge_score import rouge_scorer

THRESHOLD = 0.2  # sentences below this max ROUGE-L are flagged "unsupported"

_SCORER = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_DIR = os.path.join(_HERE, "..", "data", "sample_outputs")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def split_sentences(text: str) -> List[str]:
    """
    Split a draft into *factual* sentences, stripping inline [E#] markers.

    We deliberately drop section headers ("Timeline:", "Damages:") and very
    short label fragments: they make no factual assertion, so scoring them for
    groundedness would unfairly penalize a well-structured draft.
    """
    cleaned = re.sub(r"\[E\d+\]", "", text)
    # Protect common legal abbreviations so we don't split mid-name
    # (e.g. "Meridian Logistics, Inc." must stay one unit).
    for abbr in ("Inc.", "LLC.", "L.L.C.", "Corp.", "Co.", "Ltd.", "No.", "Esq.", "v."):
        cleaned = cleaned.replace(abbr, abbr.replace(".", "<DOT>"))

    parts: List[str] = []
    for line in cleaned.splitlines():
        line = line.strip().lstrip("-•").strip()
        if not line:
            continue
        # A standalone header line ending in ":" is a label, not a claim.
        if line.endswith(":") and len(line.split()) <= 3:
            continue
        for s in re.split(r"(?<=[.!?])\s+", line):
            s = s.strip().replace("<DOT>", ".")
            # Require a real clause: at least 4 words of actual content.
            if len(s.split()) >= 4:
                parts.append(s)
    return parts


def max_rouge_l(sentence: str, chunks: List[str]) -> float:
    """Best ROUGE-L F1 of `sentence` against any chunk."""
    best = 0.0
    for chunk in chunks:
        score = _SCORER.score(chunk, sentence)["rougeL"].fmeasure
        best = max(best, score)
    return best


def evaluate(draft_text: str, chunks: List[str]) -> dict:
    sentences = split_sentences(draft_text)
    per_sentence = [(s, max_rouge_l(s, chunks)) for s in sentences]
    scores = [sc for _, sc in per_sentence]
    avg = sum(scores) / len(scores) if scores else 0.0
    unsupported = [(s, sc) for s, sc in per_sentence if sc < THRESHOLD]
    return {
        "num_sentences": len(sentences),
        "avg_groundedness": round(avg, 4),
        "num_unsupported": len(unsupported),
        "unsupported": unsupported,
        "per_sentence": per_sentence,
    }


def print_report(title: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    print(f"  sentences            : {result['num_sentences']}")
    print(f"  avg groundedness     : {result['avg_groundedness']}  (ROUGE-L F1)")
    print(
        f"  unsupported (<{THRESHOLD}) : {result['num_unsupported']}"
    )
    for sent, score in result["unsupported"]:
        snippet = sent[:70] + ("…" if len(sent) > 70 else "")
        print(f"      [{score:.2f}] {snippet}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Groundedness eval (ROUGE-L).")
    parser.add_argument(
        "--draft",
        default=os.path.join(_OUT_DIR, "draft_v1.json"),
        help="JSON with draft_text + evidence[] (a GenerateResponse).",
    )
    parser.add_argument(
        "--edited",
        default=os.path.join(_OUT_DIR, "edited_v1.json"),
        help="JSON with edited_draft (re-scored against the same chunks).",
    )
    args = parser.parse_args()

    with open(args.draft, "r", encoding="utf-8") as fh:
        draft_doc = json.load(fh)

    chunks = [e["text"] for e in draft_doc.get("evidence", [])]
    if not chunks:
        raise SystemExit("Draft JSON has no evidence chunks to score against.")

    # --- Before: raw AI draft ------------------------------------------------
    before = evaluate(draft_doc["draft_text"], chunks)
    print_report("BEFORE operator edit (raw AI draft)", before)

    # --- After: operator-edited draft, scored vs the SAME chunks ------------
    if os.path.exists(args.edited):
        with open(args.edited, "r", encoding="utf-8") as fh:
            edited_doc = json.load(fh)
        edited_text = edited_doc.get("edited_draft") or edited_doc.get("draft_text", "")
        after = evaluate(edited_text, chunks)
        print_report("AFTER operator edit", after)

        delta = round(after["avg_groundedness"] - before["avg_groundedness"], 4)
        print("\n--- Improvement ---")
        print(f"  groundedness delta   : {delta:+}")
        print(
            f"  unsupported delta    : "
            f"{after['num_unsupported'] - before['num_unsupported']:+}"
        )

    print("\nDone.\n")


if __name__ == "__main__":
    main()
