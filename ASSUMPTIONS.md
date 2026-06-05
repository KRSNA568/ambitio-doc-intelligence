# Assumptions & Scope Decisions

These are the deliberate boundaries drawn for this v1 build. Each notes the
trade-off and how it would evolve.

### Domain scoped to legal / case documents
Field extraction and the draft prompt are tuned for case documents
(`case_number`, `parties`, `dates`, `key_facts`, relief sought). The pipeline is
generic, but prompts would need re-tuning for, say, medical or financial docs.

### Operator rules accumulate globally (not per-doc-type) in v1
Learned rules apply to every future draft regardless of document type. The
SQLite schema already stores a `doc_type` column, so per-type rule scoping is a
small follow-up (filter `get_rules()` by `doc_type`) — it's just not wired into
retrieval yet to keep v1 simple and the behavior easy to demonstrate.

### OCR fallback threshold: < 100 characters per page
A page yielding fewer than 100 characters from PyMuPDF is treated as a scan and
sent to pytesseract. This cleanly separates born-digital pages (which extract
perfectly and cheaply) from image pages (which need OCR), without OCR-ing every
page. The constant lives in `processor.MIN_CHARS_PER_PAGE`.

### Synthetic sample documents — no real PII
All documents in `data/sample_inputs/` are invented (Meridian v. Northgate and a
hypothetical hosting dispute). No real parties, case numbers, or personal data
are used, so the repo is safe to share.

### Rule extraction via prompting, not fine-tuning
Operator preferences are captured as natural-language rules injected into the
prompt, not by fine-tuning a model. This is a practical scope decision: it's
immediate, transparent (you can read exactly what was learned), reversible, and
needs no training infrastructure. The cost is that very large rule sets will
eventually consume prompt budget — at which point rules would be clustered or
summarized.

### Token approximation in chunking
Chunk sizes (~300 tokens, 50 overlap) are measured in whitespace-delimited
words rather than true model tokens. This avoids a tokenizer dependency in the
retrieval path and is accurate enough for retrieval granularity; exact token
budgeting would matter more if chunks were packed tightly against a context
limit.

### Page-number attribution is approximate after concatenation
Raw text from all pages is concatenated before chunking, so a chunk's
`page_number` is interpolated by even distribution across the known page count
rather than tracked exactly. Citations remain exact at the **chunk** level
(stable `chunk_id`); only the page label is a best guess.

### In-memory doc registry
`main.py` keeps `doc_id → structured_fields` in memory for `/generate`. Chunks
(ChromaDB) and rules (SQLite) are durable; the registry is not, so a server
restart requires re-uploading a document to regenerate its draft. A production
build would persist the registry alongside the chunks.

### Single-user / single-operator model
There is one global rule ledger; the system does not yet distinguish between
multiple operators. Multi-tenant rule sets would add an `operator_id` dimension
to the SQLite table and the retrieval filter.

---

## Known limitations & future work

### Groundedness eval is lexical (ROUGE-L), not semantic
ROUGE-L measures surface overlap. It works well when the draft and source share
vocabulary, but it **under-credits drafts generated from messy/OCR'd sources**:
the model silently corrects typos (`Agreemnt` → `Agreement`), so the clean draft
no longer lexically matches the garbled chunk even though it is correctly
grounded. The bundled `live_draft_v1.json` demonstrates this (see README → eval).
The fix is a semantic grounding score — e.g. cosine similarity between
sentence and chunk embeddings (we already load `all-MiniLM-L6-v2`), or an
NLI/entailment check. Scoped out of v1 to keep the eval dependency-light and
inspectable.

### LLM rate limits
The free-tier Gemini key is capped (≈ daily request quota). `llm.py` does a
bounded exponential backoff on `429 RESOURCE_EXHAUSTED` / `503` and otherwise
degrades gracefully (the route returns a meaningful error, never a 500). A
production deployment would use a paid tier and/or a request queue.

### OCR runs the standard pytesseract → tesseract path
Image/scanned inputs are OCR'd via pytesseract, which shells out to the
`tesseract` binary. This is the conventional Python OCR stack and works in any
normal environment; it simply requires the binary to be installed
(`brew install tesseract`).
