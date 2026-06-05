import React, { useRef, useState } from "react";
import { uploadFile } from "./api.js";

// Drag-drop / file-picker uploader. POSTs to /upload and hands the response
// (doc_id + structured fields) up to App via onUploaded.
export default function Upload({ onUploaded, onError }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState(null);

  async function handleFile(file) {
    if (!file) return;
    setFileName(file.name);
    setBusy(true);
    onError && onError(null);
    try {
      const resp = await uploadFile(file);
      onUploaded(resp);
    } catch (e) {
      onError && onError(`Upload failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    handleFile(e.dataTransfer.files?.[0]);
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed px-4 py-8 text-center text-sm transition ${
          dragging
            ? "border-sky-500 bg-sky-950/30"
            : "border-slate-700 hover:border-slate-500"
        }`}
      >
        {busy ? (
          <span className="text-sky-400">Processing {fileName}…</span>
        ) : (
          <>
            <div className="text-slate-300 font-medium">
              Drop a document here
            </div>
            <div className="text-slate-500 text-xs mt-1">
              PDF, image, or .txt · or click to browse
            </div>
            {fileName && (
              <div className="text-slate-400 text-xs mt-2">Last: {fileName}</div>
            )}
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.tiff,.txt"
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>
    </div>
  );
}
