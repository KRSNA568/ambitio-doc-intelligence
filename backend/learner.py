"""
learner.py
----------
The edit-learning loop — the differentiator of this system.

When an operator edits an AI draft, we do NOT just store the diff. A diff tells
us *what* changed for one document; it does not generalize. Instead we:

1. Compute a readable line-level diff (difflib) so the LLM can see exactly what
   the operator added, removed, or rewrote.
2. Ask the LLM to abstract that diff into 2-3 concise, reusable natural-language
   *rules* about the operator's preferences (tone, structure, detail level,
   formatting, inclusion/exclusion).
3. Persist those rules in a SQLite ledger.

On the next generation, get_rules() feeds those rules straight back into the
generator's system prompt, so the model's *next* draft already reflects what
the operator taught it — without any fine-tuning.
"""

from __future__ import annotations

import difflib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import List

import llm

_DB_PATH = os.environ.get(
    "RULES_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "operator_rules.db"),
)


# --------------------------------------------------------------------------- #
# SQLite ledger
# --------------------------------------------------------------------------- #
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_text   TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            doc_type    TEXT
        )
        """
    )
    conn.commit()
    return conn


def _store_rules(rules: List[str], doc_type: str | None) -> int:
    """Insert new rules, skipping near-duplicates. Returns total row count."""
    conn = _connect()
    existing = {
        row[0].strip().lower()
        for row in conn.execute("SELECT rule_text FROM operator_rules").fetchall()
    }
    now = datetime.now(timezone.utc).isoformat()
    for rule in rules:
        if rule.strip().lower() in existing:
            continue
        conn.execute(
            "INSERT INTO operator_rules (rule_text, created_at, doc_type) VALUES (?, ?, ?)",
            (rule.strip(), now, doc_type),
        )
        existing.add(rule.strip().lower())
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM operator_rules").fetchone()[0]
    conn.close()
    return total


def get_rules() -> List[str]:
    """Return all stored operator rules (newest last)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT rule_text FROM operator_rules ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# Diff
# --------------------------------------------------------------------------- #
def compute_diff(original: str, edited: str) -> str:
    """Human-readable unified-ish line diff between the two drafts."""
    diff = difflib.unified_diff(
        original.splitlines(),
        edited.splitlines(),
        fromfile="ai_draft",
        tofile="operator_edit",
        lineterm="",
    )
    return "\n".join(diff)


# --------------------------------------------------------------------------- #
# Rule extraction via the LLM
# --------------------------------------------------------------------------- #
_RULE_SYSTEM_PROMPT = """You are observing how a human operator edits AI-written \
legal case summaries, so that future drafts can match their preferences.

You will be given an ORIGINAL AI draft, the operator's EDITED version, and a \
DIFF. Infer what the operator generally prefers — not facts specific to this one \
document, but reusable stylistic/structural preferences.

Examples of good rules:
- "Use bullet points for any timeline of events."
- "Keep the summary under 150 words; the operator trims verbose drafts."
- "Lead with the procedural posture before the facts."
- "Refer to parties by role (Plaintiff/Defendant), not by name."

Return ONLY a JSON array of 2-3 short rule strings. No prose, no code fence.
If the edits are too trivial to generalize, return an empty array [].
"""


def extract_rules(original_draft: str, edited_draft: str, diff: str) -> List[str]:
    """Ask the LLM to abstract the edit into reusable rules."""
    user_content = (
        f"ORIGINAL AI DRAFT:\n{original_draft}\n\n"
        f"OPERATOR EDITED VERSION:\n{edited_draft}\n\n"
        f"DIFF:\n{diff}\n"
    )
    try:
        text = llm.generate_text(
            system=_RULE_SYSTEM_PROMPT,
            user=user_content,
            max_tokens=512,
        )
        rules = llm.extract_json(text)
        if not isinstance(rules, list):
            return []
        return [str(r).strip() for r in rules if str(r).strip()]
    except (ValueError, json.JSONDecodeError):
        return []
    except Exception:  # noqa: BLE001 - never let learning crash the request
        return []


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def learn_from_edit(
    original_draft: str,
    edited_draft: str,
    source_chunks: list | None = None,
    document_type: str | None = "legal",
) -> dict:
    """
    Full learning step. Returns:
      { "extracted_rules": [...], "diff": "...", "total_rules_stored": int }
    """
    diff = compute_diff(original_draft, edited_draft)

    # If nothing meaningfully changed, skip the LLM call entirely.
    if not diff.strip():
        return {
            "extracted_rules": [],
            "diff": "",
            "total_rules_stored": len(get_rules()),
        }

    rules = extract_rules(original_draft, edited_draft, diff)
    total = _store_rules(rules, document_type) if rules else len(get_rules())
    return {"extracted_rules": rules, "diff": diff, "total_rules_stored": total}


if __name__ == "__main__":  # pragma: no cover
    out = learn_from_edit(
        "The dispute began in 2021. The parties are Acme and Beta.",
        "- Dispute began: 2021\n- Plaintiff: Acme\n- Defendant: Beta",
    )
    print(json.dumps(out, indent=2))
