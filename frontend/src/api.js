// Thin fetch wrapper around the FastAPI backend.
// All calls go through the Vite proxy (/api -> http://localhost:8000).

const BASE = "/api";

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return handle(await fetch(`${BASE}/upload`, { method: "POST", body: form }));
}

export async function generateDraft(docId, query) {
  return handle(
    await fetch(`${BASE}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_id: docId,
        ...(query ? { query } : {}),
      }),
    })
  );
}

export async function submitEdit(docId, originalDraft, editedDraft) {
  return handle(
    await fetch(`${BASE}/submit-edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_id: docId,
        original_draft: originalDraft,
        edited_draft: editedDraft,
      }),
    })
  );
}

export async function getRules() {
  return handle(await fetch(`${BASE}/rules`));
}
