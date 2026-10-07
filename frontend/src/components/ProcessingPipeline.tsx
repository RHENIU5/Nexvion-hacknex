import type { DocMeta } from "../types";

export default function ProcessingPipeline({ documents }: { documents: DocMeta[] }) {
  if (!documents.length) return null;
  return (
    <section aria-label="Document processing pipeline" className="max-h-72 shrink-0 space-y-4 overflow-y-auto border-b border-gray-200 bg-white px-5 py-4">
      {documents.map(doc => (
        <div key={doc.id}>
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Processing pipeline</h2>
              <p className="mt-1 truncate text-xs text-gray-500">{doc.name}</p>
            </div>
            <span className="text-sm font-semibold text-indigo-600">{doc.progress ?? 0}%</span>
          </div>
          <div
            role="progressbar"
            aria-label={`Processing ${doc.name}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={doc.progress ?? 0}
            className="mb-4 h-2 overflow-hidden rounded-full bg-gray-100"
          >
            <div className="h-full rounded-full bg-indigo-500 transition-[width] duration-500" style={{ width: `${doc.progress ?? 0}%` }} />
          </div>
          <ol className="grid grid-cols-5 gap-1">
            {doc.steps.map((step, index) => {
              const completed = step.done;
              const active = step.active;
              const warning = step.warning;
              return (
                <li key={step.label} className="relative flex min-w-0 flex-col items-center text-center">
                  {index > 0 && (
                    <span className={`absolute right-1/2 top-3 h-px w-full ${completed || active ? "bg-emerald-400" : "bg-gray-200"}`} aria-hidden />
                  )}
                  <span className={`relative z-10 flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                    warning ? "bg-amber-100 text-amber-700"
                      : completed ? "bg-emerald-500 text-white"
                      : active ? "bg-indigo-100 text-indigo-700 ring-4 ring-indigo-50"
                        : "bg-gray-100 text-gray-400"
                  }`} title={warning ? "Vision analysis was unavailable; see document warnings." : undefined}>
                    {warning ? "!" : completed ? "✓" : index + 1}
                  </span>
                  <span className={`mt-1.5 text-[10px] leading-tight sm:text-xs ${
                    warning ? "text-amber-700"
                      : completed ? "text-emerald-700" : active ? "font-semibold text-indigo-700" : "text-gray-400"
                  }`}>{step.label}</span>
                </li>
              );
            })}
          </ol>
        </div>
      ))}
    </section>
  );
}
