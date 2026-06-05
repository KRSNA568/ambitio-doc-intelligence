import React, { useEffect, useState } from "react";
import Upload from "./Upload.jsx";
import DraftEditor from "./DraftEditor.jsx";
import EvidencePanel from "./EvidencePanel.jsx";
import { generateDraft, getRules } from "./api.js";

// Single-page orchestration. State flows top-down:
//   upload -> docId + fields
//   generate -> draft + citations + evidence
//   submit-edit (inside DraftEditor) -> refresh rules
export default function App() {
  const [doc, setDoc] = useState(null); // { doc_id, structured_fields, ... }
  const [draft, setDraft] = useState(null); // GenerateResponse
  const [rules, setRules] = useState([]);
  const [activeChunk, setActiveChunk] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function refreshRules() {
    try {
      const r = await getRules();
      setRules(r.rules || []);
    } catch (e) {
      /* non-fatal */
    }
  }

  useEffect(() => {
    refreshRules();
  }, []);

  async function handleGenerate() {
    if (!doc) return;
    setLoading(true);
    setError(null);
    try {
      const result = await generateDraft(doc.doc_id);
      setDraft(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handleUploaded(uploadResp) {
    setDoc(uploadResp);
    setDraft(null);
    setActiveChunk(null);
    setError(null);
  }

  return (
    <div className="min-h-screen font-sans">
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Ambitio · Document Intelligence
          </h1>
          <p className="text-xs text-slate-500">
            OCR → RAG → Grounded Draft → Edit-Learning Loop
          </p>
        </div>
        <RulesBadge rules={rules} />
      </header>

      {error && (
        <div className="mx-6 mt-4 rounded border border-red-800 bg-red-950/40 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <main className="grid grid-cols-1 lg:grid-cols-[380px_1fr_360px] gap-0">
        {/* Left: upload + fields */}
        <section className="border-r border-slate-800 p-6 space-y-4">
          <Upload onUploaded={handleUploaded} onError={setError} />
          {doc && (
            <button
              onClick={handleGenerate}
              disabled={loading}
              className="w-full rounded bg-sky-600 hover:bg-sky-500 disabled:opacity-50 px-4 py-2 text-sm font-medium"
            >
              {loading ? "Generating…" : "Generate Grounded Draft"}
            </button>
          )}
          {doc && <StructuredFields fields={doc.structured_fields} meta={doc} />}
        </section>

        {/* Center: editable draft */}
        <section className="p-6">
          {draft ? (
            <DraftEditor
              docId={doc.doc_id}
              draft={draft}
              activeChunk={activeChunk}
              onCiteClick={setActiveChunk}
              onLearned={refreshRules}
            />
          ) : (
            <Placeholder text="Upload a document and generate a draft to begin." />
          )}
        </section>

        {/* Right: evidence */}
        <section className="border-l border-slate-800 p-6">
          {draft ? (
            <EvidencePanel
              evidence={draft.evidence}
              citations={draft.citations}
              activeChunk={activeChunk}
              onSelect={setActiveChunk}
            />
          ) : (
            <Placeholder text="Evidence chunks will appear here." />
          )}
        </section>
      </main>
    </div>
  );
}

function RulesBadge({ rules }) {
  return (
    <div className="text-right">
      <div className="text-xs uppercase tracking-wide text-slate-500">
        Learned operator rules
      </div>
      <div className="text-sky-400 font-semibold">{rules.length}</div>
    </div>
  );
}

function StructuredFields({ fields, meta }) {
  return (
    <div className="rounded border border-slate-800 p-4 text-sm space-y-2">
      <h3 className="font-semibold text-slate-300">Extracted Fields</h3>
      <Field label="Case #" value={fields.case_number} />
      <Field label="Type" value={fields.document_type} />
      <Field label="Parties" value={(fields.parties || []).join("; ")} />
      <Field label="Dates" value={(fields.dates || []).join("; ")} />
      <div>
        <div className="text-slate-500">Key facts</div>
        <ul className="list-disc list-inside text-slate-300">
          {(fields.key_facts || []).map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      </div>
      {fields.confidence_notes && (
        <p className="text-xs text-amber-400/80 italic">
          {fields.confidence_notes}
        </p>
      )}
      <div className="pt-2 text-xs text-slate-600 border-t border-slate-800">
        {meta.pages_processed} page(s) · OCR {meta.ocr_used ? "used" : "not used"} ·{" "}
        {meta.num_chunks} chunks
      </div>
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="flex gap-2">
      <span className="text-slate-500 w-16 shrink-0">{label}</span>
      <span className="text-slate-200">{value || "—"}</span>
    </div>
  );
}

function Placeholder({ text }) {
  return (
    <div className="h-full flex items-center justify-center text-slate-600 text-sm">
      {text}
    </div>
  );
}
