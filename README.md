# Nexvion-hacknex

## DocMind — Multimodal Document Intelligence

Upload a PDF and ask questions across its text, tables, charts, diagrams, images, and scanned pages. Answers include citations that open the matching page and evidence region.

## Run
```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env        # configure the local Ollama URL and installed model
uvicorn main:app --reload --port 8001

# frontend (new terminal)
cd frontend && npm install && npm run dev     # http://localhost:5173
# If port 8000 is already in use locally, the backend runs on 8001 and Vite proxies /api there.
```
Tests: `cd backend && python -m pytest tests -q`

The backend uses Ollama's local API at `http://localhost:11434`. Install both a text model and a vision-language model (`ollama pull llama3:instruct` and `ollama pull llava`). Set `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_VISION_MODEL` in `backend/.env` to use different local models. No Anthropic API key is required; document pages are analyzed locally.

Install Tesseract OCR with English language data (`brew install tesseract` on macOS). On upload, DocMind displays a five-stage pipeline: upload, page detection, text extraction, visual analysis, and indexing. It extracts selectable text and structured tables and OCRs embedded images and scanned pages across the whole PDF. To keep large slide decks responsive, the local vision-language model analyzes at most four representative visual pages; sampled coverage is reported as a document warning. Missing OCR or vision support also appears as a warning. Check OCR formulas and model-described chart values against their cited pages.

To exercise the mixed-content workflow, upload `HNX26PSI01_multimodal_test_documents.pdf` if it is available in your document set. Example questions include “Compare production efficiency between Q2 and Q4, identify the three biggest reasons for the change, and show me the proof.” The response should cite the relevant table, chart, and supporting text; selecting a citation opens its page and highlighted region.

## How an answer is produced
1. `question_router` classifies the question (modality, math, multi-document).
2. `retriever` (BM25) selects matching passages and balances results across evidence types and selected documents.
3. `reasoning` asks the LLM for JSON: answer, claims (evidence ids + verbatim quote), calculations (expressions only).
4. `verifier` checks that cited ids exist, every quote appears verbatim in the cited chunk, and every calculation operand appears in the cited evidence.
5. `calculator` evaluates expressions with a safe AST evaluator (no `eval`) and fills `{{calc:n}}` placeholders.
6. On failure the model gets one retry; otherwise DocMind answers "I cannot reliably determine this…". No evidence → refusal without calling the LLM.

## Evidence object (unified)
`id, doc_id, document, page, section, type (text|table|chart|diagram|image|ocr), content, bounding_box (normalized x0,y0,x1,y1), confidence`

## Current limitations
- Vision descriptions and OCR can misread small labels, chart values, or equation layout; verify them against cited page regions.
- Retrieval is keyword-based (BM25), not semantic-vector search.
- Verification checks quotes and calculation operands, not every number in the prose.
- Data is stored on local disk under `backend/data/`; there is no auth.

## Processing pipeline
1. Upload and validate the PDF.
2. Detect pages, embedded images, and vector graphics.
3. Extract selectable text and OCR text.
4. Extract tables and analyze visual pages using the local Ollama vision model.
5. Index evidence with its type, page, bounding box, and confidence for retrieval and citations.
