export default function QuestionInput({ value, onChange, onSend, disabled, hint }:
  { value: string; onChange: (v: string) => void; onSend: () => void; disabled: boolean; hint?: string }) {
  return (
    <div className="border-t border-indigo-100 bg-white/25 p-3 sm:p-4">
      {hint && <div className="mb-2 text-[11px] text-slate-500">{hint}</div>}
      <div className="flex items-end gap-2 rounded-2xl border border-indigo-100 bg-white/85 p-2 shadow-sm shadow-indigo-900/5 focus-within:border-blue-300 focus-within:ring-4 focus-within:ring-blue-100/70">
        <button type="button" className="mb-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-lg text-slate-500 hover:bg-blue-50" aria-label="Attach a document" title="Select documents from the Documents panel">⌁</button>
        <textarea rows={1} value={value} onChange={e => onChange(e.target.value)} placeholder="Ask a question about your documents…"
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!disabled) onSend(); } }}
          className="max-h-40 min-h-10 flex-1 resize-y bg-transparent px-2 py-2 text-sm outline-none placeholder:text-slate-400" />
        <button onClick={() => onSend()} disabled={disabled || !value.trim()} aria-label="Send question"
          className="mb-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 text-lg text-white shadow-md shadow-blue-500/20 transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-40">➤</button>
      </div>
    </div>
  );
}
