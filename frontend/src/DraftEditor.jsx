import React, { useEffect, useMemo, useState } from "react";
import { submitEdit } from "./api.js";
import {
  buildMarkdown,
  buildReportObject,
  slug,
  triggerDownload,
} from "./exportUtils.js";

// Shows the generated draft two ways:
//   - a rendered view with clickable [E#] citation markers
//   - an editable <textarea> (monospace) the operator can rewrite
// On "Submit Edit" it POSTs original + edited text to /submit-edit, which runs
// the learner; extracted rules are shown inline and bubbled up via onLearned.
export default function DraftEditor({
  docId,
  draft,
  structuredFields,
  activeChunk,
  onCiteClick,
  onLearned,
}) {
  const [edited, setEdited] = useState(draft.draft_text);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const [copied, setCopied] = useState(false);

  const fileBase = `case-summary-${slug(structuredFields?.case_number || docId)}`;

  function handleDownloadMd() {
    triggerDownload(
      `${fileBase}.md`,
      buildMarkdown({ docId, fields: structuredFields, draft, editedText: edited }),
      "text/markdown"
    );
  }

  function handleDownloadJson() {
    triggerDownload(
      `${fileBase}.json`,
      JSON.stringify(
        buildReportObject({ docId, fields: structuredFields, draft, editedText: edited }),
        null,
        2
      ),
      "application/json"
    );
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(edited);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      setErr("Clipboard copy blocked by the browser.");
    }
  }

  // Reset editor when a fresh draft arrives.
  useEffect(() => {
    setEdited(draft.draft_text);
    setResult(null);
    setErr(null);
  }, [draft]);

  // label ("E1") -> chunk_id, for marker clicks.
  const labelToChunk = useMemo(() => {
    const m = {};
    (draft.evidence || []).forEach((e) => (m[e.label] = e.chunk_id));
    return m;
  }, [draft]);

  async function handleSubmit() {
    setSubmitting(true);
    setErr(null);
    try {
      const r = await submitEdit(docId, draft.draft_text, edited);
      setResult(r);
      onLearned && onLearned();
    } catch (e) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold text-slate-200">Case Fact Summary</h2>
        <div className="flex items-center gap-2">
          {draft.applied_rules?.length > 0 && (
            <span className="text-xs text-emerald-400 mr-1">
              {draft.applied_rules.length} rule(s) applied
            </span>
          )}
          <button
            onClick={handleCopy}
            className="rounded border border-slate-700 hover:border-slate-500 px-2.5 py-1 text-xs text-slate-300"
            title="Copy the current draft text"
          >
            {copied ? "Copied ✓" : "Copy"}
          </button>
          <button
            onClick={handleDownloadMd}
            className="rounded border border-slate-700 hover:border-slate-500 px-2.5 py-1 text-xs text-slate-300"
            title="Download a formatted report (fields + draft + evidence)"
          >
            ↓ .md
          </button>
          <button
            onClick={handleDownloadJson}
            className="rounded border border-slate-700 hover:border-slate-500 px-2.5 py-1 text-xs text-slate-300"
            title="Download the full structured output as JSON"
          >
            ↓ .json
          </button>
        </div>
      </div>

      {/* Rendered view with clickable citations */}
      <div className="rounded border border-slate-800 bg-slate-950/50 p-4 font-mono text-sm leading-relaxed whitespace-pre-wrap">
        <RenderedDraft
          text={draft.draft_text}
          labelToChunk={labelToChunk}
          activeChunk={activeChunk}
          onCiteClick={onCiteClick}
        />
      </div>

      {/* Editable textarea */}
      <div>
        <label className="text-xs uppercase tracking-wide text-slate-500">
          Edit the draft, then submit to teach the system
        </label>
        <textarea
          value={edited}
          onChange={(e) => setEdited(e.target.value)}
          rows={12}
          className="mt-1 w-full rounded border border-slate-800 bg-slate-950 p-3 font-mono text-sm text-slate-200 focus:border-sky-600 focus:outline-none"
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={submitting || edited === draft.draft_text}
          className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-4 py-2 text-sm font-medium"
        >
          {submitting ? "Learning…" : "Submit Edit"}
        </button>
        {edited === draft.draft_text && (
          <span className="text-xs text-slate-600">
            Make an edit to enable submission
          </span>
        )}
      </div>

      {err && <p className="text-sm text-red-400">{err}</p>}

      {result && (
        <div className="rounded border border-emerald-900 bg-emerald-950/30 p-4 text-sm">
          <h3 className="font-semibold text-emerald-300 mb-2">
            Extracted {result.extracted_rules.length} reusable rule(s)
          </h3>
          {result.extracted_rules.length === 0 ? (
            <p className="text-slate-400">
              Edit was too minor to generalize into a rule.
            </p>
          ) : (
            <ul className="list-disc list-inside text-slate-200 space-y-1">
              {result.extracted_rules.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          <p className="text-xs text-slate-500 mt-2">
            Total rules now stored: {result.total_rules_stored}. Generate again
            to see them applied.
          </p>
        </div>
      )}
    </div>
  );
}

// Splits draft text on [E#] markers and renders the markers as clickable spans.
function RenderedDraft({ text, labelToChunk, activeChunk, onCiteClick }) {
  const parts = text.split(/(\[E\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[(E\d+)\]$/);
        if (match) {
          const label = match[1];
          const chunkId = labelToChunk[label];
          const isActive = chunkId && chunkId === activeChunk;
          return (
            <span
              key={i}
              className={`cite-marker ${isActive ? "cite-active" : ""}`}
              onClick={() => chunkId && onCiteClick(chunkId)}
              title={chunkId ? `Trace to ${chunkId}` : label}
            >
              {part}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}
