import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ask, listDocs, removeDoc, uploadDocs } from "./api";
import ChatPanel from "./components/ChatPanel";
import DocumentSidebar from "./components/DocumentSidebar";
import EvidenceViewer from "./components/EvidenceViewer";
import Header from "./components/Header";
import ProcessingPipeline from "./components/ProcessingPipeline";
import QuestionInput from "./components/QuestionInput";
import type { DocMeta, Message, Source, ViewerTarget } from "./types";

export default function App() {
  const [docs, setDocs] = useState<DocMeta[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [tab, setTab] = useState<"chat" | "evidence">("chat");
  const [search, setSearch] = useState("");
  const seen = useRef(new Set<string>());
  const nextId = useRef(1);
  const usable = useMemo(() => docs.filter(d => d.status === "ready" && selected.has(d.id)), [docs, selected]);
  const visibleDocs = useMemo(() => docs.filter(d => d.name.toLowerCase().includes(search.trim().toLowerCase())), [docs, search]);

  const refresh = useCallback(async () => {
    try {
      const list = await listDocs();
      setDocs(list);
      const fresh = list.filter(d => d.status === "ready" && !seen.current.has(d.id));
      if (fresh.length) {
        fresh.forEach(d => seen.current.add(d.id));
        setSelected(s => new Set([...s, ...fresh.map(d => d.id)]));
      }
    } catch { /* backend not reachable yet */ }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!docs.some(d => d.status === "processing")) return;
    const t = setInterval(refresh, 1200);
    return () => clearInterval(t);
  }, [docs, refresh]);
  const upload = async (files: File[]) => {
    setUploading(true);
    try { await uploadDocs(files); await refresh(); } finally { setUploading(false); }
  };
  const open = (docId: string, page: number, bbox?: number[] | null) => { setViewer({ docId, page, bbox }); setTab("evidence"); };
  const send = async (question = input) => {
    const q = question.trim();
    if (!q || busy || !usable.length) return;
    const uid = nextId.current++, aid = nextId.current++;
    setMessages(m => [...m, { id: uid, role: "user", text: q }, { id: aid, role: "assistant", pending: true }]);
    setInput(""); setBusy(true);
    try {
      const response = await ask(q, usable.map(d => d.id));
      setMessages(m => m.map(x => x.id === aid ? { id: aid, role: "assistant", response } : x));
      if (response.sources[0]) { const s = response.sources[0]; setViewer({ docId: s.doc_id, page: s.page, bbox: s.bbox }); }
    } catch (e) {
      setMessages(m => m.map(x => x.id === aid ? { id: aid, role: "assistant", error: (e as Error).message } : x));
    } finally { setBusy(false); }
  };

  const viewDoc = docs.find(d => d.id === viewer?.docId);
  const hasPreview = Boolean(viewDoc && viewer);
  const sidebar = (
    <DocumentSidebar docs={visibleDocs} selected={selected} uploading={uploading}
      search={search}
      onToggle={id => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; })}
      onUpload={upload} onView={id => open(id, 1)}
      onQuickAsk={send}
      onRemove={async id => { await removeDoc(id); setSelected(s => { const n = new Set(s); n.delete(id); return n; }); if (viewer?.docId === id) setViewer(null); refresh(); }} />
  );

  return (
    <div className="dashboard-shell flex h-full flex-col">
      <Header onMenu={() => setDrawer(d => !d)} search={search} onSearch={setSearch} />
      <div className={`relative grid min-h-0 flex-1 gap-3 p-3 sm:p-4 lg:grid-cols-[250px_minmax(0,1fr)] ${hasPreview ? "xl:grid-cols-[270px_minmax(420px,1fr)_minmax(320px,0.72fr)] 2xl:grid-cols-[300px_minmax(520px,1fr)_420px]" : "xl:grid-cols-[270px_minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(0,1fr)]"}`}>
        <div className={`${drawer ? "absolute inset-y-3 left-3 z-20 w-[min(84vw,320px)] shadow-2xl" : "hidden"} glass-panel min-h-0 overflow-hidden lg:static lg:block lg:w-auto lg:shadow-none`}>{sidebar}</div>

        <main className={`${tab === "chat" ? "flex" : "hidden"} glass-panel min-h-0 flex-col overflow-hidden lg:flex`}>
          <div className="flex border-b border-indigo-100 text-sm lg:hidden">
            <button className="flex-1 border-b-2 border-blue-600 py-2 font-medium">Chat</button>
            <button className="flex-1 py-2 text-gray-500" onClick={() => setTab("evidence")}>Preview</button>
          </div>
          <ProcessingPipeline documents={docs.filter(d => d.status === "processing")} />
          <ChatPanel messages={messages} onQuickAsk={send} quickAskDisabled={busy || !usable.length}
            onOpen={(s: Source) => open(s.doc_id, s.page, s.bbox)} />
          <QuestionInput value={input} onChange={setInput} onSend={send} disabled={busy || !usable.length}
            hint={!usable.length ? "Upload and select a processed PDF to ask questions." : `Asking across ${usable.length} selected document${usable.length > 1 ? "s" : ""}`} />
        </main>

        <section className={`${tab === "evidence" ? "flex" : "hidden"} glass-panel min-h-0 flex-col overflow-hidden ${hasPreview ? "xl:flex" : "xl:hidden"}`}>
          <div className="flex border-b border-indigo-100 text-sm lg:hidden">
            <button className="flex-1 py-2 text-gray-500" onClick={() => setTab("chat")}>Chat</button>
            <button className="flex-1 border-b-2 border-blue-600 py-2 font-medium">Preview</button>
          </div>
          <div className="min-h-0 flex-1"><EvidenceViewer doc={viewDoc} target={viewer} onPage={p => viewer && setViewer({ ...viewer, page: p, bbox: null })} /></div>
        </section>
      </div>
    </div>
  );
}
