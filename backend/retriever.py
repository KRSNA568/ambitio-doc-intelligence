"""
retriever.py
------------
RAG layer: chunk -> embed -> store -> retrieve.

- Chunking: ~300-token sliding windows with 50-token overlap. Overlap keeps a
  fact from being split across a boundary so it stays retrievable. We
  approximate "tokens" with whitespace words (fast, dependency-free, and close
  enough for retrieval granularity on legal prose).
- Embeddings: sentence-transformers all-MiniLM-L6-v2, computed locally so the
  pipeline needs no embedding API and runs offline.
- Store: a persistent ChromaDB collection. Each chunk carries a *stable*
  chunk_id ("{doc_id}::chunk::{index}") so a citation in a draft can always be
  traced back to exact source text, even across restarts.
"""

from __future__ import annotations

import os
from typing import List

import chromadb
from chromadb.config import Settings

from models import RetrievedChunk

# ----- Tunables ------------------------------------------------------------ #
CHUNK_SIZE_TOKENS = 300
CHUNK_OVERLAP_TOKENS = 50
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "legal_chunks"

# Persist next to the backend package so it survives restarts.
_CHROMA_DIR = os.environ.get(
    "CHROMA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".chroma"),
)


# --------------------------------------------------------------------------- #
# Lazy singletons — heavy objects we only want to build once per process.
# --------------------------------------------------------------------------- #
_embed_model = None
_chroma_client = None
_collection = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(
            path=_CHROMA_DIR,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def chroma_ready() -> bool:
    """Cheap health probe used by /health."""
    try:
        _get_collection()
        return True
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
def _chunk_text(text: str) -> List[str]:
    """Sliding-window word chunks with overlap."""
    words = text.split()
    if not words:
        return []

    chunks: List[str] = []
    step = CHUNK_SIZE_TOKENS - CHUNK_OVERLAP_TOKENS
    for start in range(0, len(words), step):
        window = words[start : start + CHUNK_SIZE_TOKENS]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + CHUNK_SIZE_TOKENS >= len(words):
            break
    return chunks


def _approx_page_number(chunk_index: int, total_chunks: int, total_pages: int) -> int:
    """
    Map a chunk to a best-guess page so citations can reference a page.
    We do not have per-chunk page offsets after concatenation, so we
    distribute chunks evenly across the known page count.
    """
    if total_chunks <= 0 or total_pages <= 0:
        return 1
    return min(total_pages, 1 + (chunk_index * total_pages) // total_chunks)


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #
def ingest(doc_id: str, text: str, total_pages: int = 1) -> int:
    """
    Chunk, embed, and store a document. Returns the number of chunks stored.
    Re-ingesting the same doc_id first clears its old chunks (idempotent).
    """
    collection = _get_collection()

    # Drop any prior version of this doc so re-uploads don't duplicate.
    try:
        collection.delete(where={"doc_id": doc_id})
    except Exception:  # noqa: BLE001 - empty collection is fine
        pass

    chunks = _chunk_text(text)
    if not chunks:
        return 0

    model = _get_embed_model()
    embeddings = model.encode(chunks, normalize_embeddings=True).tolist()

    ids, metadatas, documents = [], [], []
    for idx, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}::chunk::{idx}"
        ids.append(chunk_id)
        documents.append(chunk)
        metadatas.append(
            {
                "doc_id": doc_id,
                "chunk_index": idx,
                "page_number": _approx_page_number(idx, len(chunks), total_pages),
                "raw_text": chunk,
            }
        )

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )
    return len(chunks)


# --------------------------------------------------------------------------- #
# Retrieve
# --------------------------------------------------------------------------- #
def retrieve(query: str, doc_id: str, top_k: int = 5) -> List[RetrievedChunk]:
    """Return the top_k most similar chunks for `query` within `doc_id`."""
    collection = _get_collection()
    model = _get_embed_model()
    query_embedding = model.encode([query], normalize_embeddings=True).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        where={"doc_id": doc_id},
    )

    out: List[RetrievedChunk] = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    for chunk_id, text, meta, dist in zip(ids, docs, metas, dists):
        # cosine distance -> similarity score in [0, 1]
        score = round(1.0 - float(dist), 4)
        out.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                doc_id=meta.get("doc_id", doc_id),
                chunk_index=int(meta.get("chunk_index", 0)),
                page_number=int(meta.get("page_number", 1)),
                text=text,
                score=score,
            )
        )
    return out


if __name__ == "__main__":  # pragma: no cover
    n = ingest("demo", "The dispute began in March 2021. " * 200, total_pages=2)
    print(f"stored {n} chunks")
    for c in retrieve("when did the dispute begin", "demo", top_k=3):
        print(c.chunk_id, c.score, c.text[:60])
