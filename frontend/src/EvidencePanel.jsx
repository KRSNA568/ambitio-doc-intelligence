import React from "react";

// Sidebar listing each [E#] evidence block with its source text. Clicking a
// block (or a citation marker in the draft) highlights the matching chunk so
// the operator can verify grounding at a glance.
export default function EvidencePanel({
  evidence,
  citations,
  activeChunk,
  onSelect,
}) {
  // Which sentences cite a given chunk_id (reverse of the citations map).
  const chunkToSentences = {};
  Object.entries(citations || {}).forEach(([sid, chunkIds]) => {
    chunkIds.forEach((cid) => {
      (chunkToSentences[cid] = chunkToSentences[cid] || []).push(sid);
    });
  });

  return (
    <div className="space-y-3">
      <h2 className="font-semibold text-slate-200">Evidence</h2>
      <p className="text-xs text-slate-500">
        Each draft sentence is grounded in one of these source chunks.
      </p>
      {(evidence || []).map((e) => {
        const isActive = e.chunk_id === activeChunk;
        const sentences = chunkToSentences[e.chunk_id] || [];
        return (
          <div
            key={e.chunk_id}
            onClick={() => onSelect(e.chunk_id)}
            className={`cursor-pointer rounded border p-3 text-sm transition ${
              isActive
                ? "border-sky-500 bg-sky-950/40"
                : "border-slate-800 hover:border-slate-600"
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="font-mono text-sky-400 font-semibold">
                [{e.label}]
              </span>
              <span className="text-xs text-slate-500">
                p.{e.page_number} · sim {e.score}
              </span>
            </div>
            <p className="text-slate-300 text-xs leading-relaxed line-clamp-6">
              {e.text}
            </p>
            {sentences.length > 0 && (
              <div className="mt-2 text-[10px] text-slate-500">
                cited by {sentences.join(", ")}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
