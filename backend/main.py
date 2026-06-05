"""
main.py
-------
FastAPI application wiring the four modules into a pipeline:

    /upload      processor -> retriever.ingest          -> doc_id + fields
    /generate    retriever.retrieve -> generator        -> grounded draft
    /submit-edit learner.learn_from_edit                -> operator rules
    /rules       learner.get_rules                       -> stored rules
    /health      liveness + dependency readiness

The app keeps a tiny in-memory registry of processed docs (structured fields +
page count) so /generate can reuse them. Chunks themselves live in ChromaDB and
rules live in SQLite, so the only thing lost on restart is this lightweight
registry — re-upload to repopulate.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from typing import Dict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import generator
import learner
import llm
import processor
import retriever
from models import (
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    RulesResponse,
    StructuredFields,
    SubmitEditRequest,
    SubmitEditResponse,
    UploadResponse,
)

app = FastAPI(title="Ambitio Doc Intelligence", version="1.0.0")

# Frontend runs on a different port (Vite). Allow it during local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# In-memory doc registry: doc_id -> {structured_fields, pages, doc_type}
_DOC_REGISTRY: Dict[str, dict] = {}


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        llm_key_set=llm.api_key_set(),
        chroma_ready=retriever.chroma_ready(),
    )


# --------------------------------------------------------------------------- #
# /upload
# --------------------------------------------------------------------------- #
@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    """Accept a file, run OCR + field extraction, ingest chunks into Chroma."""
    suffix = os.path.splitext(file.filename or "")[1] or ".bin"
    tmp_path = None
    try:
        # Persist the upload to a temp file so PyMuPDF/pytesseract can read it.
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        result = processor.process_document(tmp_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Processing failed: {exc}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    doc_id = uuid.uuid4().hex[:12]

    try:
        num_chunks = retriever.ingest(
            doc_id=doc_id,
            text=result.raw_text,
            total_pages=result.pages_processed,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")

    _DOC_REGISTRY[doc_id] = {
        "structured_fields": result.structured_fields,
        "pages": result.pages_processed,
        "doc_type": result.structured_fields.document_type or "legal",
    }

    return UploadResponse(
        doc_id=doc_id,
        structured_fields=result.structured_fields,
        pages_processed=result.pages_processed,
        ocr_used=result.ocr_used,
        num_chunks=num_chunks,
    )


# --------------------------------------------------------------------------- #
# /generate
# --------------------------------------------------------------------------- #
@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    """Retrieve evidence and produce a grounded draft, applying learned rules."""
    entry = _DOC_REGISTRY.get(req.doc_id)
    if entry is None:
        # The doc may still be in Chroma after a restart; fall back to empty
        # fields rather than refusing outright.
        structured = StructuredFields(
            confidence_notes="Doc not in registry (server restarted?). "
            "Retrieval will still work if chunks remain in Chroma."
        )
    else:
        structured = entry["structured_fields"]

    try:
        chunks = retriever.retrieve(req.query, req.doc_id, top_k=req.top_k)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}")

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for doc_id={req.doc_id}. Upload it first.",
        )

    rules = learner.get_rules()
    return generator.generate_draft(
        doc_id=req.doc_id,
        structured_fields=structured,
        retrieved_chunks=chunks,
        operator_rules=rules,
    )


# --------------------------------------------------------------------------- #
# /submit-edit
# --------------------------------------------------------------------------- #
@app.post("/submit-edit", response_model=SubmitEditResponse)
def submit_edit(req: SubmitEditRequest) -> SubmitEditResponse:
    """Learn reusable operator rules from an edited draft."""
    doc_type = req.document_type
    entry = _DOC_REGISTRY.get(req.doc_id)
    if entry:
        doc_type = entry.get("doc_type", doc_type)

    try:
        out = learner.learn_from_edit(
            original_draft=req.original_draft,
            edited_draft=req.edited_draft,
            document_type=doc_type,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Learning failed: {exc}")

    return SubmitEditResponse(
        extracted_rules=out["extracted_rules"],
        diff=out["diff"],
        total_rules_stored=out["total_rules_stored"],
    )


# --------------------------------------------------------------------------- #
# /rules
# --------------------------------------------------------------------------- #
@app.get("/rules", response_model=RulesResponse)
def rules() -> RulesResponse:
    return RulesResponse(rules=learner.get_rules())
