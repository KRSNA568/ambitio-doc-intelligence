"""
models.py
---------
Pydantic schemas for every request/response that flows through the API.

Keeping these in one place means the frontend contract is documented in a
single file, and every other module imports its types from here rather than
re-declaring dict shapes inline.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Processor output
# --------------------------------------------------------------------------- #
class StructuredFields(BaseModel):
    """Structured fields extracted from a raw legal document by the LLM."""

    case_number: Optional[str] = None
    parties: List[str] = Field(default_factory=list)
    dates: List[str] = Field(default_factory=list)
    key_facts: List[str] = Field(default_factory=list)
    document_type: Optional[str] = None
    confidence_notes: Optional[str] = None


class ProcessResult(BaseModel):
    """Everything the processor knows about a freshly ingested document."""

    raw_text: str
    structured_fields: StructuredFields
    pages_processed: int
    ocr_used: bool


# --------------------------------------------------------------------------- #
# Retriever
# --------------------------------------------------------------------------- #
class RetrievedChunk(BaseModel):
    """A single chunk returned from the vector store, with provenance."""

    chunk_id: str
    doc_id: str
    chunk_index: int
    page_number: int
    text: str
    score: float


# --------------------------------------------------------------------------- #
# API: /upload
# --------------------------------------------------------------------------- #
class UploadResponse(BaseModel):
    doc_id: str
    structured_fields: StructuredFields
    pages_processed: int
    ocr_used: bool
    num_chunks: int


# --------------------------------------------------------------------------- #
# API: /generate
# --------------------------------------------------------------------------- #
class GenerateRequest(BaseModel):
    doc_id: str
    query: str = Field(
        default="Summarize the key facts, parties, dates, and dispute of this case.",
        description="Retrieval query used to pull grounding evidence.",
    )
    top_k: int = 5


class EvidenceBlock(BaseModel):
    """An [E#] evidence block surfaced to the operator alongside the draft."""

    label: str          # e.g. "E1"
    chunk_id: str
    page_number: int
    text: str
    score: float


class GenerateResponse(BaseModel):
    doc_id: str
    draft_text: str
    # sentence_id -> list of chunk_ids that ground that sentence
    citations: Dict[str, List[str]]
    evidence: List[EvidenceBlock]
    applied_rules: List[str]


# --------------------------------------------------------------------------- #
# API: /submit-edit
# --------------------------------------------------------------------------- #
class SubmitEditRequest(BaseModel):
    doc_id: str
    original_draft: str
    edited_draft: str
    document_type: Optional[str] = "legal"


class SubmitEditResponse(BaseModel):
    extracted_rules: List[str]
    diff: str
    total_rules_stored: int


# --------------------------------------------------------------------------- #
# API: /rules
# --------------------------------------------------------------------------- #
class RulesResponse(BaseModel):
    rules: List[str]


# --------------------------------------------------------------------------- #
# API: /health
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str
    llm_key_set: bool
    chroma_ready: bool
