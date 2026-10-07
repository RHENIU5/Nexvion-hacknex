"""Local Ollama vision analysis for figures, charts, and diagrams in PDF pages."""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request

import fitz


class VisionError(RuntimeError):
    """Raised when the configured local vision model cannot analyze a page."""


_availability_lock = threading.Lock()
_availability_cache: tuple[float, bool] = (0.0, False)


def model_available() -> bool:
    global _availability_cache
    now = time.monotonic()
    with _availability_lock:
        checked_at, available = _availability_cache
        if now - checked_at < 30:
            return available

    model = os.getenv("OLLAMA_VISION_MODEL", "llava:latest")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/api/show",
        data=json.dumps({"name": model}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            details = json.loads(response.read())
            available = isinstance(details, dict) and "vision" in details.get("capabilities", [])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        available = False
    with _availability_lock:
        _availability_cache = (now, available)
    return available


def analyze_page(page: fitz.Page, page_number: int, has_native_table: bool = False) -> list[dict]:
    model = os.getenv("OLLAMA_VISION_MODEL", "llava:latest")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    scale = min(1.0, 768 / max(page.rect.width, page.rect.height))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 500},
        "messages": [{
            "role": "user",
            "content": (
                f"Inspect page {page_number} of a document. Report only visible tables, charts, graphs, "
                "plots, diagrams, photographs, or other meaningful visuals. "
                f"Text-based tables already extracted: {str(has_native_table).lower()}. "
                "Skip tables already extracted from PDF text; still extract image-only tables, but include "
                "at most 4 rows and 6 cells per row. Never repeat or pad table cells. "
                "Do not summarize "
                "ordinary paragraphs or invent unreadable values. For each visual, provide its "
                "type (table, chart, diagram, or image), a short label, a description of at most 15 words, and a "
                "normalized [x0,y0,x1,y1] bounding box from 0 to 1 relative to this page. "
                "Return at most 1 visual. Keep the description to one short sentence and under 20 words. "
                "For charts, include the visible title, axes, series, and trends only when legible. "
                "For tables, include \"rows\": [[\"header\", \"value\"]]. "
                "Return JSON exactly as {\"visuals\": [{\"type\": \"table|chart|diagram|image\", "
                "\"label\": \"...\", \"description\": \"...\", \"rows\": [], \"bbox\": [0,0,1,1]}]}. "
                "Return an empty visuals list when there is no meaningful visual."
            ),
            "images": [image],
        }],
    }
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise VisionError(f"Vision analysis failed on page {page_number}: {error}") from error

    message = result.get("message") if isinstance(result, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    try:
        parsed = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as error:
        raise VisionError(f"Vision model returned invalid JSON on page {page_number}.") from error
    if not isinstance(parsed, dict):
        raise VisionError(f"Vision model returned invalid JSON on page {page_number}.")
    visuals = parsed.get("visuals")
    if not isinstance(visuals, list):
        raise VisionError(f"Vision model returned invalid JSON on page {page_number}.")

    evidence = []
    for visual in visuals[:8]:
        if not isinstance(visual, dict):
            continue
        kind = visual.get("type")
        label = visual.get("label")
        description = visual.get("description")
        if kind not in {"table", "chart", "diagram", "image"} or not isinstance(description, str) or not description.strip():
            continue
        if not isinstance(label, str) or not label.strip():
            label = kind.capitalize()
        content = f"{label.strip()}: {description.strip()}"
        if kind == "table":
            rows = visual.get("rows")
            if not isinstance(rows, list) or not rows:
                continue
            normalized_rows = [
                [str(cell).strip()[:200] for cell in row[:20]]
                for row in rows[:60] if isinstance(row, list)
            ]
            if not normalized_rows:
                continue
            content = "\n".join([f"Table — {label.strip()}", *(" | ".join(row) for row in normalized_rows)])
        bbox = visual.get("bbox")
        if (
            not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in bbox)
            or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]
        ):
            bbox = [0.0, 0.0, 1.0, 1.0]
        evidence.append({
            "type": kind,
            "label": label.strip()[:120],
            "content": content,
            "bounding_box": [float(value) for value in bbox],
            "confidence": 0.7,
        })
    return evidence
