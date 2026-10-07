import { useEffect, useRef } from "react";
import type { Message, Source } from "../types";
import AnswerCard from "./AnswerCard";

const SAMPLES = [
  "Summarize this document",
  "Compare the main findings",
  "Extract key numbers",
  "Find supporting evidence",
];

export default function ChatPanel({ messages, onOpen, onQuickAsk, quickAskDisabled }:
  { messages: Message[]; onOpen: (s: Source) => void; onQuickAsk: (q: string) => void; quickAskDisabled: boolean }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (!messages.length) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-6 text-center">
        <div className="assistant-avatar mb-4" aria-hidden>✦</div>
        <h1 className="text-xl font-semibold text-slate-800">Ask your documents anything</h1>
        <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">Get clear answers from your PDFs, with a page citation for every source.</p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {SAMPLES.map(q => (
            <button key={q} onClick={() => onQuickAsk(q)} disabled={quickAskDisabled}
              className="rounded-full border border-indigo-100 bg-white/70 px-3 py-2 text-xs font-medium text-slate-700 shadow-sm transition hover:border-blue-300 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50">
              {q}
            </button>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="flex-1 space-y-4 overflow-y-auto p-3 sm:p-4">
      {messages.map(m => m.role === "user" ? (
        <div key={m.id} className="flex justify-end">
          <div className="max-w-[88%] rounded-2xl rounded-br-md bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-3 text-sm text-white shadow-md shadow-blue-500/10">
            {m.text}<div className="mt-1 text-right text-[10px] text-blue-100">You</div>
          </div>
        </div>
      ) : (
        <div key={m.id} className="flex items-start gap-2.5">
          <div className="assistant-avatar mt-1 shrink-0" aria-hidden>✦</div>
          <div className="min-w-0 flex-1">
            {m.pending && <div className="answer-panel p-4 text-sm text-slate-500">Searching your documents…</div>}
            {m.error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{m.error}</div>}
            {m.response && <AnswerCard r={m.response} onOpen={onOpen} />}
          </div>
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}
