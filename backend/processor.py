"""
processor.py
------------
Document ingestion: turn a messy PDF or image into (a) clean raw text and
(b) structured legal fields.

Strategy
========
1. Try PyMuPDF (fitz) text extraction first — fast, exact, free for any
   born-digital PDF.
2. If a page yields very little text (< MIN_CHARS_PER_PAGE), assume it is a
   scan/photo and fall back to pytesseract OCR on a rendered raster of that
   page. Image inputs (.png/.jpg/...) go straight to OCR.
3. Send the recovered text to the LLM (Gemini) and ask for a strict JSON
   object of structured fields. The LLM is the only component that can read
   *meaning* out of inconsistent legal formatting, so we lean on it for field
   extraction rather than brittle regexes.

Every external call (OCR, LLM) is wrapped so a single failure degrades
gracefully instead of taking down the request.
"""

from __future__ import annotations

import json
import os
from typing import Tuple

import fitz  # PyMuPDF

import llm
from models import ProcessResult, StructuredFields

# ----- Tunables ------------------------------------------------------------ #
MIN_CHARS_PER_PAGE = 100          # OCR fallback threshold (see ASSUMPTIONS.md)
OCR_RENDER_DPI = 300              # higher DPI -> better OCR on faint scans
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"}


# --------------------------------------------------------------------------- #
# OCR helpers
# --------------------------------------------------------------------------- #
def _ocr_image_bytes(image_bytes: bytes) -> str:
    """Run pytesseract over raw image bytes."""
    import io

    import pytesseract
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(img)
    except Exception as exc:  # noqa: BLE001 - report, never crash the request
        return f"[OCR_ERROR: {exc}]"


def _ocr_pdf_page(page: "fitz.Page") -> str:
    """Render a PDF page to a raster and OCR it."""
    pix = page.get_pixmap(dpi=OCR_RENDER_DPI)
    return _ocr_image_bytes(pix.tobytes("png"))


# --------------------------------------------------------------------------- #
# Raw text extraction
# --------------------------------------------------------------------------- #
def _extract_text(file_path: str) -> Tuple[str, int, bool]:
    """
    Return (raw_text, pages_processed, ocr_used).

    Handles both PDFs (text-first, OCR fallback per page) and image files
    (OCR only).
    """
    ext = os.path.splitext(file_path)[1].lower()

    # --- Plain image: OCR directly ---------------------------------------- #
    if ext in IMAGE_EXTENSIONS:
        with open(file_path, "rb") as fh:
            text = _ocr_image_bytes(fh.read())
        return text, 1, True

    # --- Plain text file: trivial passthrough (useful for synthetic .txt) -- #
    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), 1, False

    # --- PDF: text-first, OCR per sparse page ----------------------------- #
    doc = fitz.open(file_path)
    pages_out: list[str] = []
    ocr_used = False

    for page in doc:
        page_text = page.get_text("text") or ""
        if len(page_text.strip()) < MIN_CHARS_PER_PAGE:
            ocr_text = _ocr_pdf_page(page)
            if len(ocr_text.strip()) > len(page_text.strip()):
                page_text = ocr_text
                ocr_used = True
        pages_out.append(page_text)

    pages_processed = doc.page_count
    doc.close()
    return "\n\n".join(pages_out), pages_processed, ocr_used


# --------------------------------------------------------------------------- #
# Structured field extraction via the LLM
# --------------------------------------------------------------------------- #
_FIELD_SYSTEM_PROMPT = """You are a legal document analyst. You will be given the \
raw, possibly messy or OCR-garbled text of a single legal/case document.

Extract the following fields and return ONLY a JSON object (no prose, no code \
fence) with exactly these keys:

{
  "case_number": string or null,
  "parties": [list of party names, e.g. "Plaintiff: Acme Corp"],
  "dates": [list of relevant dates as written, with what they refer to],
  "key_facts": [3-7 short factual statements drawn ONLY from the text],
  "document_type": short string (e.g. "Complaint", "Settlement Agreement"),
  "confidence_notes": string noting anything ambiguous, missing, or likely an \
OCR error
}

Rules:
- Never invent a value. If a field is absent, use null or an empty list.
- key_facts must be grounded in the supplied text, not general knowledge.
- Keep each fact under 25 words.
"""


def _extract_fields(raw_text: str) -> StructuredFields:
    """Ask the LLM for structured fields; degrade gracefully on any failure."""
    # Guard against empty / OCR-failed documents before spending a token.
    if not raw_text or not raw_text.strip():
        return StructuredFields(
            confidence_notes="No extractable text found in the document."
        )

    try:
        # Cap the text we send so a huge doc doesn't blow the context window.
        excerpt = raw_text[:18000]
        text = llm.generate_text(
            system=_FIELD_SYSTEM_PROMPT,
            user=excerpt,
            max_tokens=1024,
        )
        data = llm.extract_json(text)
        return StructuredFields(**data)
    except (ValueError, json.JSONDecodeError) as exc:
        return StructuredFields(
            confidence_notes=f"Field extraction returned non-JSON: {exc}"
        )
    except Exception as exc:  # noqa: BLE001
        return StructuredFields(
            confidence_notes=f"Field extraction failed: {exc}"
        )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def process_document(file_path: str) -> ProcessResult:
    """
    Full ingestion of one document.

    Returns a ProcessResult with raw_text, structured_fields, pages_processed
    and an ocr_used flag.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No such file: {file_path}")

    raw_text, pages_processed, ocr_used = _extract_text(file_path)
    structured = _extract_fields(raw_text)

    return ProcessResult(
        raw_text=raw_text,
        structured_fields=structured,
        pages_processed=pages_processed,
        ocr_used=ocr_used,
    )


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import sys

    result = process_document(sys.argv[1])
    print(f"pages={result.pages_processed} ocr_used={result.ocr_used}")
    print(result.structured_fields.model_dump_json(indent=2))
