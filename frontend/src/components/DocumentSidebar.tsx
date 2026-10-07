import { useRef, useState } from "react";
import type { DocMeta } from "../types";

interface Props {
  docs: DocMeta[]; selected: Set<string>; uploading: boolean;
  search: string;
  onToggle: (id: string) => void; onUpload: (files: File[]) => void;
  onView: (id: string) => void; onRemove: (id: string) => void;
  onQuickAsk: (question: string) => void;
}

const PROMPTS = [
  "Compare the main findings",
  "What are the main reasons for the change?",
  "Show supporting charts and tables",
  "Extract the key numbers",
  "Summarize all selected documents",
];

function warningSummary(warnings: string[]) {
  const sample = warnings.find(warning => warning.startsWith("Visual analysis sampled "));
  const sampleMatch = sample?.match(/sampled (\d+) of (\d+) visual pages/);
  const failedPages = new Set(
    warnings.flatMap(warning => {
      const match = warning.match(/Visual analysis could not run on pages ([\d, ]+)/);
      return match ? match[1].split(",").map(page => page.trim()) : [];
    }),
  );
  const ocrWarning = warnings.find(warning => warning.startsWith("OCR text was extracted from "));
  const ocrMatch = ocrWarning?.match(/from (\d+) page/);
  const ocrPages = new Set(
    warnings.flatMap(warning => {
      const match = warning.match(/^Page (\d+) includes image text extracted with OCR/);
      return match ? [match[1]] : [];
    }),
  );
  const summary = [
    sampleMatch && `Vision ${sampleMatch[1]}/${sampleMatch[2]} pages`,
    failedPages.size > 0 && `Vision unavailable on ${failedPages.size} ${failedPages.size === 1 ? "page" : "pages"}`,
    (ocrMatch?.[1] || ocrPages.size) &&
      `OCR on ${ocrMatch?.[1] || ocrPages.size} ${Number(ocrMatch?.[1] || ocrPages.size) === 1 ? "page" : "pages"}`,
  ].filter(Boolean);

  return summary.length ? summary.join(" · ") : warnings[0];
}

export default function DocumentSidebar({ docs, selected, uploading, search, onToggle, onUpload, onView, onRemove, onQuickAsk }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [menu, setMenu] = useState<string | null>(null);
  return (
    <aside className="flex h-full flex-col gap-3 overflow-y-auto p-3 sm:p-4">
      <section className="sidebar-section">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <svg aria-hidden width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3.5 6.5h6l2 2H20a1 1 0 0 1 1 1v8.75a1.25 1.25 0 0 1-1.25 1.25H4.25A1.25 1.25 0 0 1 3 18.25V7a.5.5 0 0 1 .5-.5Z" /></svg>
          Documents
        </h2>
        <button onClick={() => input.current?.click()} disabled={uploading}
          className="rounded-xl bg-gradient-to-r from-blue-500 to-violet-600 px-3 py-2 text-xs font-semibold text-white shadow-md shadow-blue-500/20 transition hover:brightness-105 disabled:opacity-50">
          {uploading ? "Uploading…" : "+ Upload"}
        </button>
        <input ref={input} type="file" accept="application/pdf" multiple hidden
          onChange={e => { const f = Array.from(e.target.files ?? []); if (f.length) onUpload(f); e.target.value = ""; }} />
      </div>

      {docs.length === 0 && (
        <button onClick={() => input.current?.click()}
          className="rounded-xl border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500 hover:border-blue-400">
          {search ? "No matching documents." : "Upload one or more PDFs to start asking questions."}
        </button>
      )}

      <ul className="space-y-2 overflow-y-auto">
        {docs.map(d => (
          <li key={d.id} className={`document-row relative ${selected.has(d.id) ? "document-row-selected" : ""}`}>
            <div className="flex items-start gap-2.5">
              <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-blue-600" disabled={d.status !== "ready"}
                checked={selected.has(d.id)} onChange={() => onToggle(d.id)} aria-label={`Use ${d.name}`} />
              <div className="min-w-0 flex-1">
                <button type="button" className="flex w-full min-w-0 items-center gap-2 text-left" onClick={() => d.status === "ready" && onView(d.id)}>
                  <span className="pdf-badge">PDF</span>
                  <span className="truncate text-[13px] font-semibold text-slate-800" title={d.name}>{d.name}</span>
                </button>
                {d.status === "ready" && <div className="mt-1 pl-8 text-xs text-slate-500">{d.pages} pages</div>}
                {d.status === "error" && <div className="mt-1 text-xs text-red-600">{d.error}</div>}
                {d.status === "processing" && (
                  <div className="mt-2">
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-blue-500" style={{ width: `${d.progress ?? 0}%` }} /></div>
                    <span className="mt-1 block text-[11px] text-slate-500">Processing · {d.progress ?? 0}%</span>
                  </div>
                )}
                {d.status === "ready" && d.warnings.length > 0 && (
                  <details className="mt-1 text-[11px] text-amber-700">
                    <summary className="cursor-pointer list-none">
                      <span className="block truncate" title={warningSummary(d.warnings)}>
                        {warningSummary(d.warnings)}
                      </span>
                      <span className="mt-0.5 inline-block text-[11px] text-slate-500 underline decoration-dotted underline-offset-2">
                        Details ({d.warnings.length})
                      </span>
                    </summary>
                    <ul className="mt-1 max-h-32 space-y-1 overflow-y-auto border-l border-amber-200 pl-2 text-[11px] leading-snug">
                      {d.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}
                    </ul>
                  </details>
                )}
              </div>
              <button onClick={() => setMenu(menu === d.id ? null : d.id)} aria-label="Document menu" className="px-1 text-gray-400 hover:text-gray-700">⋮</button>
            </div>
            {menu === d.id && (
              <div className="absolute right-2 top-9 z-10 w-28 rounded-lg border border-gray-200 bg-white py-1 text-sm shadow-sm">
                <button className="block w-full px-3 py-1.5 text-left hover:bg-gray-50 disabled:text-gray-300" disabled={d.status !== "ready"}
                  onClick={() => { onView(d.id); setMenu(null); }}>View</button>
                <button className="block w-full px-3 py-1.5 text-left text-red-600 hover:bg-gray-50"
                  onClick={() => { onRemove(d.id); setMenu(null); }}>Remove</button>
              </div>
            )}
          </li>
        ))}
      </ul>
      </section>

      <section className="sidebar-section">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <span className="text-lg text-violet-600" aria-hidden>✦</span>
          Try asking
        </h2>
        <div className="space-y-1.5">
          {PROMPTS.map(prompt => (
            <button key={prompt} onClick={() => onQuickAsk(prompt)} disabled={!selected.size}
              className="suggestion-row">
              <span>{prompt}</span><span aria-hidden className="text-base text-slate-400">›</span>
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}
