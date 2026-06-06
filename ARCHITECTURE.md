# Architecture

## Pipeline overview

```
                          ┌──────────────────────────────────────────────┐
                          │                  FastAPI (main.py)            │
                          └──────────────────────────────────────────────┘
                                  │            │             │
        ┌─────────────────────────┘            │             └──────────────────────┐
        ▼ /upload                               ▼ /generate                          ▼ /submit-edit
┌───────────────┐                       ┌───────────────┐                    ┌───────────────┐
│ processor.py  │                       │ retriever.py  │                    │  learner.py   │
│               │                       │  .retrieve()  │                    │               │
│ PyMuPDF text  │   raw_text            │      │        │  top-k chunks      │ difflib diff  │
│   │           │ ───────────┐          │      ▼        │ ─────────────┐     │      │        │
│   ▼ sparse?   │            │          │ ChromaDB      │              ▼     │      ▼        │
│ pytesseract   │            ▼          │ (persistent)  │       ┌───────────────┐  Gemini rule│
│   │           │     retriever.py      └───────────────┘       │ generator.py  │  extraction │
│   ▼           │     .ingest()                ▲                │ Gemini draft  │      │      │
│ Gemini field  │   chunk+embed                │ operator_rules │ with [E#]     │      ▼      │
│ extraction    │   (MiniLM) → Chroma          └────────────────┤ citations     │  SQLite     │
└───────────────┘                                               └───────────────┘  ledger     │
        │                                                               │          └───────────┘
        ▼                                                               ▼                ▲
 structured_fields                                          draft + citation map         │
                                                                        │                │
                                                            operator edits the draft ────┘
                                                                  (closes the loop)
```

The data contract between every stage lives in `models.py`, so each module can
be imported and unit-tested on its own. The three stages that call the LLM
(`processor`, `generator`, `learner`) all go through a single access point,
`llm.py`, so the provider/model lives in exactly one file.

---

## Module-by-module design decisions

### `processor.py` — extraction with a graceful OCR fallback
Born-digital PDFs are extracted with **PyMuPDF**, which is exact and free. Only
when a page yields fewer than `MIN_CHARS_PER_PAGE` (100) characters do we render
that page to a 300-DPI raster and run **pytesseract** — paying the slow OCR cost
only where it's actually needed. Image inputs go straight to OCR; `.txt` is a
pass-through for the synthetic samples. Structured-field extraction is delegated
to **Gemini** with a strict JSON contract rather than regexes, because legal
formatting is too inconsistent for pattern matching and the model is explicitly
instructed never to invent a missing value.

### `retriever.py` — RAG with traceable chunks
Text is split into ~300-token sliding windows with 50-token overlap; the overlap
prevents a fact from being cut across a boundary and becoming unretrievable.
Chunks are embedded **locally** with `all-MiniLM-L6-v2` (no embedding API,
offline-capable) and stored in a **persistent ChromaDB** collection using cosine
distance. The critical detail is the **stable `chunk_id`** (`{doc_id}::chunk::{i}`):
it is the spine of the whole citation system — every claim in a draft can be
traced to exact source text, even across restarts.

### `generator.py` — grounded generation, no hallucination
Retrieved chunks are injected as numbered `[E1]…[Ek]` evidence blocks. The
system prompt makes three hard demands: cite the supporting block after every
factual sentence, never assert anything absent from the evidence, and obey any
operator rules supplied. The model also returns a machine-readable
`sentence → [E#]` map, which we translate from labels back to stable
`chunk_id`s so the UI can highlight the source of any sentence. A regex fallback
reconstructs the citation map from inline markers if the model omits the JSON.

### `learner.py` — the edit-learning loop *(key differentiator)*
See the dedicated section below.

### `llm.py` — single LLM access point
`processor`, `generator`, and `learner` all need text generation, so rather than
duplicate client code three times, every call routes through `llm.generate_text()`.
This means one file knows which provider/model/SDK is in use (Google Gemini via
the `google-genai` SDK, `gemini-2.5-flash` by default, `GEMINI_MODEL`-overridable)
— swapping providers or models is a one-file change and each caller stays
provider-agnostic. Two Gemini-specific concerns are handled here once for
everyone: (1) **thinking is disabled** (`thinking_budget=0`) because Gemini 2.5
draws thinking tokens from `max_output_tokens` and can otherwise truncate JSON
mid-string; (2) **transient `429`/`503` errors are retried** with bounded
exponential backoff that honors the server's `retryDelay`. `llm.extract_json()`
also lives here — a lenient parser (strips ```` ``` ```` fences, `raw_decode`s the
first value) that makes Gemini's fenced/trailing-prose output safe to parse.

### `main.py` — orchestration
A thin FastAPI layer that sequences the modules and holds a small in-memory
registry mapping `doc_id → structured_fields` so `/generate` can reuse upload
results. Durable state (chunks, rules) lives in ChromaDB and SQLite; only the
lightweight registry is lost on restart, recoverable by re-uploading. Every
external call is wrapped so one failure returns a meaningful error instead of a
crash.

---

## The edit-learning loop (why this is the interesting part)

A naive "learn from edits" system stores the diff and replays it. That doesn't
generalize: a diff for *Meridian v. Northgate* says nothing useful about the
*next* case. We want to capture the operator's **transferable preferences**, not
their document-specific keystrokes.

**Step 1 — observe the edit.**
`/submit-edit` receives the original AI draft and the operator's edited version.
`difflib` produces a readable line-level diff so the model can see exactly what
was added, removed, or rewritten.

**Step 2 — abstract, don't memorize.**
The diff (plus both full drafts for context) goes to Gemini with a prompt that
asks for **2–3 concise, reusable rules** about tone, structure, detail level,
formatting, and inclusion/exclusion — explicitly *not* facts about this one
document. Example output:
- *"Present the chronology of events as a bulleted timeline with dates."*
- *"Refer to parties by litigation role (Plaintiff/Defendant), not by name."*
- *"Keep the summary concise; trim connective prose."*

**Step 3 — persist.**
Rules are written to a SQLite `operator_rules(id, rule_text, created_at,
doc_type)` ledger, de-duplicated against existing rules.

**Step 4 — apply automatically.**
On the next `/generate`, `learner.get_rules()` returns the full rule set, which
`main.py` passes into `generator.py`, where it is injected verbatim into the
system prompt. The next draft therefore arrives **already** in the operator's
preferred shape — without any model fine-tuning, and the effect compounds as
more edits accumulate.

`data/sample_outputs/` ships a worked example of this exact loop:
`draft_v1.json` (verbose prose) → `edited_v1.json` (operator restructures) →
`extracted_rules.json` (three learned rules) → `draft_v2_with_rules.json` (a new
document that is already terse, role-based, and timeline-formatted).
