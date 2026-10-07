import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from anthropic import AuthenticationError

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from document_processor import DocumentStore
from question_router import classify
from reasoning import answer_question
from retriever import is_summary_request, requested_pages, retrieve

MAX_BYTES = int(os.getenv("DOCMIND_MAX_UPLOAD_MB", "50")) * 1024 * 1024
store = DocumentStore(Path(__file__).parent / "data")
logger = logging.getLogger(__name__)

app = FastAPI(title="DocMind")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/documents")
def list_documents(background: BackgroundTasks):
    for doc_id in store.schedule_stale_documents():
        background.add_task(store.process, doc_id)
    return store.list()


@app.post("/api/documents")
async def upload(background: BackgroundTasks, files: list[UploadFile] = File(...)):
    out = []
    for f in files:
        data = await f.read()
        name = os.path.basename(f.filename or "document.pdf")[:120]
        err = None
        if not name.lower().endswith(".pdf") or not data.startswith(b"%PDF"):
            err = "Only PDF files are supported."
        elif len(data) > MAX_BYTES:
            err = f"This file is larger than {MAX_BYTES // 1024 // 1024} MB."
        meta = store.create(name, data, error=err)
        if not err:
            background.add_task(store.process, meta["id"])
        out.append(meta)
    return out


@app.delete("/api/documents/{doc_id}")
def remove(doc_id: str):
    if not store.delete(doc_id):
        raise HTTPException(404, "Document not found")
    return {"ok": True}


@app.get("/api/documents/{doc_id}/pages/{page}/image")
def page_image(doc_id: str, page: int, scale: float = 1.5):
    path = store.page_image(doc_id, page, scale)
    if not path:
        raise HTTPException(404, "Page not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    document_ids: list[str]


@app.post("/api/chat")
def chat(req: ChatRequest):
    ready = [d for d in req.document_ids if (store.get(d) or {}).get("status") == "ready"]
    if not ready:
        raise HTTPException(400, "Select at least one processed document.")
    route = classify(req.question, len(ready))
    evidence = store.evidence(ready)
    pages = requested_pages(req.question)
    vision_warnings = []
    if pages:
        visual_evidence, vision_warnings = store.inspect_pages(ready, pages)
        evidence.extend(visual_evidence)
    hits = (
        evidence
        if is_summary_request(req.question) or pages
        else retrieve(req.question, evidence)
    )
    try:
        result = answer_question(req.question, hits, route)
        result["checks"].extend(vision_warnings)
        return result
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except AuthenticationError:
        raise HTTPException(
            503,
            "Ollama rejected the request. Check that Ollama is running and the configured model is available.",
        )
    except Exception:
        logger.exception("AI service failed while answering a chat request")
        raise HTTPException(502, "The AI service returned an error. Please try again.")
