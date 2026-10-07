import type { EvidenceType, Source } from "../types";

const ICON: Record<EvidenceType, string> = { text: "¶", table: "▦", chart: "▥", image: "▣", diagram: "◇", ocr: "⌗" };

export default function SourceList({ sources, onOpen }: { sources: Source[]; onOpen: (s: Source) => void }) {
  if (!sources.length) return null;
  return (
    <div className="mt-4">
      <div className="mb-2 text-xs font-semibold text-slate-700">Sources</div>
      <ul className="space-y-2">
        {sources.map(s => (
          <li key={s.evidence_id}>
            <button onClick={() => onOpen(s)}
              className="source-row w-full rounded-xl border border-indigo-100 bg-white/65 p-3 text-left hover:border-blue-300 hover:bg-blue-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="text-blue-600" aria-hidden>{ICON[s.type] ?? "¶"}</span>
                  <span className="truncate font-medium">{s.label}</span>
                </span>
                <span className="shrink-0 text-blue-600">Page {s.page} →</span>
              </div>
              <div className="mt-0.5 truncate text-xs text-gray-500">{s.document}</div>
              <div className="mt-1 line-clamp-2 text-xs text-gray-600">“{s.snippet}”</div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
