import { pageImage } from "../api";
import type { DocMeta, ViewerTarget } from "../types";
import PageThumbnails from "./PageThumbnails";

export default function EvidenceViewer({ doc, target, onPage }: { doc?: DocMeta; target: ViewerTarget | null; onPage: (p: number) => void }) {
  if (!doc || !target) {
    return <div className="flex h-full items-center justify-center p-6 text-center text-sm text-gray-500">Select a source to see the exact page it came from.</div>;
  }
  const { page, bbox } = target;
  const btn = "flex h-8 w-8 items-center justify-center rounded-lg border border-indigo-100 bg-white/75 text-sm text-slate-600 transition hover:border-blue-300 hover:text-blue-700 disabled:opacity-40";
  return (
    <div className="flex h-full flex-col bg-white/15">
      <div className="flex items-center justify-between gap-2 border-b border-indigo-100 px-3 py-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="pdf-badge">PDF</span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-800">{doc.name}</div>
            <div className="text-xs text-slate-500">Page {page} of {doc.pages}</div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button className={btn} onClick={() => onPage(Math.max(1, page - 1))} disabled={page <= 1} aria-label="Previous page">‹</button>
          <button className={btn} onClick={() => onPage(Math.min(doc.pages, page + 1))} disabled={page >= doc.pages} aria-label="Next page">›</button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 items-start justify-center overflow-auto bg-gradient-to-br from-slate-100/80 to-indigo-50/60 p-3 sm:p-4">
        <div className="relative mx-auto w-full max-w-[540px]">
          <img src={pageImage(doc.id, page, Math.min(2, window.devicePixelRatio || 1.5))} alt={`${doc.name} page ${page}`} className="document-page block w-full bg-white" />
          {bbox && (
            <div className="pointer-events-none absolute rounded-sm border-2 border-blue-600 bg-blue-500/15"
              style={{ left: `${bbox[0] * 100}%`, top: `${bbox[1] * 100}%`, width: `${(bbox[2] - bbox[0]) * 100}%`, height: `${(bbox[3] - bbox[1]) * 100}%` }} />
          )}
        </div>
      </div>
      <div className="border-t border-indigo-100 bg-white/25">
        <PageThumbnails docId={doc.id} page={page} total={doc.pages} onSelect={onPage} />
      </div>
    </div>
  );
}
