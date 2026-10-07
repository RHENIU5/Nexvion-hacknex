import ReactMarkdown from "react-markdown";
import type { ChatResponse, Source } from "../types";
import SourceList from "./SourceList";

const BADGE = { High: "bg-green-50 text-green-700", Medium: "bg-blue-50 text-blue-700", Low: "bg-red-50 text-red-700" };

export default function AnswerCard({ r, onOpen }: { r: ChatResponse; onOpen: (s: Source) => void }) {
  if (r.status === "insufficient") {
    return (
      <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm leading-relaxed text-gray-700">
        {r.answer.split("\n\n").map((p, i) => <p key={i} className={i ? "mt-2" : "font-medium"}>{p}</p>)}
      </div>
    );
  }
  return (
    <div className="answer-panel p-4 sm:p-5">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
        <span className="text-blue-600" aria-hidden>✦</span>
        Document answer
      </div>
      <div className="prose-answer text-sm text-slate-700"><ReactMarkdown>{r.answer}</ReactMarkdown></div>

      {r.calculations.length > 0 && (
        <div className="mt-4 rounded-lg bg-gray-50 p-3 text-xs text-gray-600">
          <div className="mb-1 font-medium text-gray-700">Calculations</div>
          {r.calculations.map((c, i) => (
            <div key={i} className="font-mono">{c.label && `${c.label}: `}{c.expression} = <span className="text-green-700">{c.result}</span></div>
          ))}
        </div>
      )}

      <SourceList sources={r.sources} onOpen={onOpen} />

      <div className="mt-4 border-t border-gray-100 pt-3 text-xs text-gray-600">
        <span className={`rounded-full px-2 py-0.5 font-medium ${BADGE[r.confidence]}`}>Confidence: {r.confidence}</span>
        <ul className="mt-2 space-y-0.5">{r.checks.map(c => <li key={c}><span className="text-green-600">✓</span> {c}</li>)}</ul>
      </div>
    </div>
  );
}
