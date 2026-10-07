export interface DocMeta {
  id: string; name: string; pages: number; status: "processing" | "ready" | "error";
  steps: { label: string; done: boolean; active?: boolean; warning?: boolean }[]; progress?: number;
  error?: string | null; warnings: string[];
}
export type EvidenceType = "text" | "table" | "chart" | "diagram" | "image" | "ocr";
export interface Source {
  evidence_id: string; doc_id: string; document: string; page: number; type: EvidenceType;
  section?: string | null; label: string; snippet: string; bbox: number[] | null; confidence: number;
}
export interface Calc { label: string; expression: string; result: number }
export interface ChatResponse {
  status: "answered" | "insufficient"; answer: string; sources: Source[];
  confidence: "High" | "Medium" | "Low"; checks: string[]; calculations: Calc[];
}
export interface Message { id: number; role: "user" | "assistant"; text?: string; response?: ChatResponse; pending?: boolean; error?: string }
export interface ViewerTarget { docId: string; page: number; bbox?: number[] | null }
