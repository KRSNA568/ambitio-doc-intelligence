// Helpers to view/export the generated output as a downloadable file.

// Trigger a browser download of `content` as `filename`.
export function triggerDownload(filename, content, mime = "text/plain") {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// A short slug for filenames, e.g. "CV-2021-08842" -> "cv-2021-08842".
export function slug(s) {
  return (s || "case")
    .toString()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40) || "case";
}

// Build the full machine-readable record (fields + draft + evidence + rules).
export function buildReportObject({ docId, fields, draft, editedText }) {
  return {
    doc_id: docId,
    generated_at: new Date().toISOString(),
    structured_fields: fields || null,
    draft_text: draft.draft_text,
    edited_draft: editedText !== draft.draft_text ? editedText : undefined,
    citations: draft.citations,
    evidence: draft.evidence,
    applied_rules: draft.applied_rules,
  };
}

// Build a human-readable Markdown report.
export function buildMarkdown({ docId, fields, draft, editedText }) {
  const f = fields || {};
  const lines = [];
  lines.push("# Case Fact Summary");
  lines.push("");
  lines.push(`*Generated ${new Date().toLocaleString()} · doc \`${docId}\`*`);
  lines.push("");

  lines.push("## Extracted Fields");
  lines.push(`- **Case number:** ${f.case_number || "—"}`);
  lines.push(`- **Document type:** ${f.document_type || "—"}`);
  lines.push(`- **Parties:** ${(f.parties || []).join("; ") || "—"}`);
  lines.push(`- **Dates:** ${(f.dates || []).join("; ") || "—"}`);
  if ((f.key_facts || []).length) {
    lines.push(`- **Key facts:**`);
    f.key_facts.forEach((k) => lines.push(`  - ${k}`));
  }
  if (f.confidence_notes) lines.push(`- **Notes:** ${f.confidence_notes}`);
  lines.push("");

  lines.push("## Draft (grounded, with citations)");
  lines.push("");
  lines.push(editedText || draft.draft_text);
  lines.push("");

  if (editedText && editedText !== draft.draft_text) {
    lines.push("> Note: this is the operator-edited version. The original AI draft is in the JSON export.");
    lines.push("");
  }

  if (draft.applied_rules && draft.applied_rules.length) {
    lines.push("## Operator rules applied");
    draft.applied_rules.forEach((r) => lines.push(`- ${r}`));
    lines.push("");
  }

  lines.push("## Evidence");
  (draft.evidence || []).forEach((e) => {
    lines.push(`### [${e.label}] — page ${e.page_number} · similarity ${e.score}`);
    lines.push(`\`${e.chunk_id}\``);
    lines.push("");
    lines.push(e.text);
    lines.push("");
  });

  return lines.join("\n");
}
