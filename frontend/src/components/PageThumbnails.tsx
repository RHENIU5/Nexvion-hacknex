import { pageImage } from "../api";

export default function PageThumbnails({ docId, page, total, onSelect }: { docId: string; page: number; total: number; onSelect: (p: number) => void }) {
  const start = Math.max(1, Math.min(page - 2, total - 4));
  const pages = Array.from({ length: Math.min(5, total) }, (_, i) => start + i);
  return (
    <div className="flex items-center justify-center gap-2 overflow-hidden p-3">
      {pages.map(p => (
        <button key={p} onClick={() => onSelect(p)} aria-label={`Page ${p}`}
          className={`w-12 shrink-0 overflow-hidden rounded-lg border-2 transition sm:w-14 ${p === page ? "border-blue-500 shadow-sm shadow-blue-500/20" : "border-white/80 hover:border-blue-300"}`}>
          <img src={pageImage(docId, p, 0.3)} alt="" loading="lazy" className="block w-full" />
          <div className={`py-0.5 text-center text-[10px] ${p === page ? "bg-blue-50 font-semibold text-blue-700" : "bg-white/70 text-gray-600"}`}>{p}</div>
        </button>
      ))}
    </div>
  );
}
