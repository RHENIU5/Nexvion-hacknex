import type { ChatResponse, DocMeta } from "./types";

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = "Something went wrong. Please try again.";
    try { msg = (await r.json()).detail ?? msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return r.json();
}
export const listDocs = () => fetch("/api/documents").then(r => json<DocMeta[]>(r));
export const uploadDocs = (files: File[]) => {
  const fd = new FormData(); files.forEach(f => fd.append("files", f));
  return fetch("/api/documents", { method: "POST", body: fd }).then(r => json<DocMeta[]>(r));
};
export const removeDoc = (id: string) => fetch(`/api/documents/${id}`, { method: "DELETE" });
export const ask = (question: string, document_ids: string[]) =>
  fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, document_ids }) })
    .then(r => json<ChatResponse>(r));
export const pageImage = (id: string, page: number, scale = 1.5) => `/api/documents/${id}/pages/${page}/image?scale=${scale}`;
