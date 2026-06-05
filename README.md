# Ambitio · Document Intelligence

An end-to-end pipeline that ingests messy legal documents, extracts structured
text via OCR, retrieves grounded evidence with RAG, and generates a fully
**cited** Case Fact Summary — then learns reusable natural-language rules from
operator edits so every subsequent draft matches the operator's style.

The differentiator is the **edit-learning loop**: the system doesn't just store
diffs, it abstracts each operator edit into reusable preferences (e.g. *"present
the chronology as a bulleted timeline"*) and applies them to future drafts with
no fine-tuning.

---

## Architecture at a glance

```
PDF / image / txt
      │
      ▼
 processor.py ──► OCR (PyMuPDF → pytesseract fallback) + Gemini field extraction
      │                                   │
      │ raw_text                          ▼  structured_fields
      ▼                          { case_number, parties, dates, key_facts, ... }
 retriever.py ──► chunk + embed (all-MiniLM-L6-v2) ──► ChromaDB (persistent)
      │
      │ top-k chunks (stable chunk_ids)
      ▼
 generator.py ──► Gemini draft with inline [E#] citations  ◄── operator_rules
      │                                                          ▲
      │ draft + citation map                                     │
      ▼                                                          │
   operator edits the draft ──► learner.py ──► Gemini rule extraction
                                                   │
                                                   ▼
                                         SQLite operator_rules ledger
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the per-module rationale and a
detailed explanation of the learning loop.

---

## Setup (under 10 minutes)

### 1. Prerequisites
- Python 3.10+
- Node 18+ (only for the frontend)
- **Tesseract** binary (for scanned/image OCR):
  - macOS: `brew install tesseract`
  - Ubuntu: `sudo apt-get install tesseract-ocr`
  - (Born-digital PDFs and the bundled `.txt` samples work without it.)

### 2. Backend
```bash
cd ambitio-doc-intelligence
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY=...                   # required for fields/draft/rules
uvicorn main:app --app-dir backend --reload --port 8000
```
Check it's alive: `curl localhost:8000/health`

### 3. Frontend (optional UI)
```bash
cd frontend
npm install
npm run dev      # http://localhost:5173  (proxies /api → :8000)
```

---

## Run the full pipeline

### Via the UI
1. Open http://localhost:5173
2. Drag in `data/sample_inputs/02_messy_case_summary.txt`
3. See the extracted structured fields → click **Generate Grounded Draft**
4. Read the draft; click any `[E1]`/`[E2]` marker to highlight its source chunk
5. Edit the draft (e.g. turn the facts into a bulleted timeline) → **Submit Edit**
6. The panel shows the **reusable rules** the system just learned
7. Upload another doc and **Generate** again — the rules are already applied

### Via the API (curl)
```bash
# 1. Upload → get a doc_id
DOC=$(curl -s -F "file=@data/sample_inputs/01_clean_case_summary.txt" \
      localhost:8000/upload | python -c "import sys,json;print(json.load(sys.stdin)['doc_id'])")

# 2. Generate a grounded draft
curl -s localhost:8000/generate -H "Content-Type: application/json" \
     -d "{\"doc_id\":\"$DOC\"}" | python -m json.tool

# 3. Teach it from an edit
curl -s localhost:8000/submit-edit -H "Content-Type: application/json" \
     -d "{\"doc_id\":\"$DOC\",\"original_draft\":\"...\",\"edited_draft\":\"...\"}"

# 4. Inspect learned rules
curl -s localhost:8000/rules | python -m json.tool
```

### Endpoints
| Method | Route          | Purpose                                          |
|--------|----------------|--------------------------------------------------|
| POST   | `/upload`      | OCR + field extraction + Chroma ingest → doc_id  |
| POST   | `/generate`    | Retrieve evidence + generate cited draft         |
| POST   | `/submit-edit` | Learn reusable rules from an operator edit       |
| GET    | `/rules`       | List all stored operator rules                   |
| GET    | `/health`      | Liveness + dependency readiness                  |

---

## Run the evaluation

```bash
pip install -r requirements.txt          # includes rouge-score
python eval/eval.py
```

This scores the bundled `data/sample_outputs/draft_v1.json` for groundedness
(per-sentence max ROUGE-L vs. source chunks), reports unsupported sentences
(ROUGE-L < 0.2), and compares the raw AI draft against the operator-edited
version. Point it at your own outputs with `--draft` / `--edited`.

**Headline result** (clean-source draft, `draft_v1.json`): avg groundedness
≈ **0.56**, 1 borderline sentence (the framing opener).

**Live output** is also bundled — `live_draft_v1.json` / `live_edited_v1.json`
were produced by the running system (Gemini) from the *messy* sample doc:

```bash
python eval/eval.py --draft data/sample_outputs/live_draft_v1.json \
                    --edited data/sample_outputs/live_edited_v1.json
```

This live run scores *low* (≈ 0.11, most sentences flagged), which is a real
and instructive finding rather than a grounding failure: the model normalizes
the source's heavy OCR typos (`plaintff`, `Agreemnt`, `breech`...) in its draft,
so a purely **lexical** metric like ROUGE-L can no longer match the clean draft
to the garbled source even though the draft is correctly grounded. The takeaway:
lexical groundedness under-credits drafts built from messy/OCR'd inputs — a
semantic (embedding-based) grounding score is the right next step (see
ASSUMPTIONS.md → future work).

### Unit tests

```bash
pip install pytest
python -m pytest tests/ -q        # 26 tests: chunking, citations, JSON, diff/rules, eval
```

---

## Docker (optional)

```bash
export GEMINI_API_KEY=...
docker compose up --build
# backend → http://localhost:8000 , frontend → http://localhost:5173
```

---

## Repo layout
```
backend/    FastAPI app + the pipeline modules (each importable alone) + llm.py
frontend/   React + Tailwind single-page UI
data/       synthetic sample inputs (incl. a real scanned PNG) + sample outputs
eval/       ROUGE-L groundedness evaluation
tests/      pytest unit suite (26 tests, no network needed)
*.md        README / ARCHITECTURE / ASSUMPTIONS
```

## Sample inputs
- `01_clean_case_summary.txt` — born-digital, text-based
- `02_messy_case_summary.txt` — typo-ridden, inconsistent formatting
- `03_handwritten_note.txt` — terse, abbreviated intake note
- `04_scanned_notice.png` — a **real degraded scan** (grayscale, skew, noise)
  that exercises the pytesseract OCR path. Regenerate with
  `python data/sample_inputs/generate_scanned_sample.py`. Requires the
  `tesseract` binary (`brew install tesseract`).
