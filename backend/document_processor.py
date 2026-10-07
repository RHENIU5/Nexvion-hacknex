"""Document store: saves uploads, runs processing, renders page images."""
import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import fitz

from pdf_parser import PARSER_VERSION, PDFError, parse_pdf
from vision_processor import VisionError, analyze_page, model_available

STEPS = ["Upload", "Page Detection", "Text Extraction", "Visual Analysis", "Indexing"]
logger = logging.getLogger(__name__)


class DocumentStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._meta: dict[str, dict] = {}
        self._evidence: dict[str, list] = {}
        self._processing: set[str] = set()
        self._queued: set[str] = set()
        for d in self.root.iterdir():
            mf, ef = d / "meta.json", d / "evidence.json"
            if mf.exists():
                self._meta[d.name] = json.loads(mf.read_text())
                self._evidence[d.name] = json.loads(ef.read_text()) if ef.exists() else []

    def _dir(self, doc_id): return self.root / doc_id

    def _save_meta(self, doc_id):
        (self._dir(doc_id) / "meta.json").write_text(json.dumps(self._meta[doc_id]))

    def _steps(self, active: int | None = None, done: int = 0):
        return [
            {"label": label, "done": i < done, "active": i == active}
            for i, label in enumerate(STEPS)
        ]

    def create(self, name: str, data: bytes, error: str | None = None) -> dict:
        doc_id = uuid.uuid4().hex
        self._dir(doc_id).mkdir(parents=True)
        if not error:
            (self._dir(doc_id) / "original.pdf").write_bytes(data)
        meta = {"id": doc_id, "name": name, "pages": 0, "status": "error" if error else "processing",
                "steps": self._steps(active=1 if not error else None, done=1 if not error else 0),
                "progress": 10 if not error else 0, "error": error, "warnings": [], "created": time.time()}
        with self._lock:
            self._meta[doc_id] = meta
            self._evidence[doc_id] = []
            self._save_meta(doc_id)
        return meta

    def process(self, doc_id: str):
        with self._lock:
            self._queued.discard(doc_id)
            if doc_id in self._processing:
                return
            self._processing.add(doc_id)
        try:
            self._process(doc_id)
        finally:
            with self._lock:
                self._processing.discard(doc_id)

    def _process(self, doc_id: str):
        meta = self._meta[doc_id]
        meta.update(status="processing", error=None)
        self._save_meta(doc_id)

        progress_ranges = {
            "page_detection": (1, 10, 20),
            "text_extraction": (2, 20, 50),
            "visual_analysis": (3, 50, 85),
        }

        def progress(stage: str, done: int, total: int):
            active, start, end = progress_ranges[stage]
            meta["steps"] = self._steps(active=active, done=1)
            meta["progress"] = round(start + (end - start) * done / max(total, 1))
            self._save_meta(doc_id)

        try:
            res = parse_pdf(self._dir(doc_id) / "original.pdf", doc_id, meta["name"], progress)
            meta["steps"] = self._steps(active=4, done=4)
            meta["progress"] = 85
            self._evidence[doc_id] = res.evidence
            (self._dir(doc_id) / "evidence.json").write_text(json.dumps(res.evidence))
            meta.update(pages=res.pages, warnings=res.warnings)
            meta["parser_version"] = PARSER_VERSION
            vision_warning = next(
                (warning for warning in res.warnings if warning.startswith("Visual analysis could not run")),
                "",
            )
            meta["vision_incomplete"] = bool(vision_warning)
            meta["vision_retryable"] = any(
                phrase in vision_warning
                for phrase in ("HTTP Error 404", "Connection refused", "Connection reset")
            )
            meta["vision_model"] = os.getenv("OLLAMA_VISION_MODEL", "llava:latest")
            meta["steps"] = self._steps(done=5)
            if meta["vision_incomplete"]:
                meta["steps"][3]["warning"] = True
            meta["progress"] = 100
            meta["status"] = "ready"
        except PDFError as e:
            meta.update(status="error", error=str(e))
            meta["steps"] = self._steps()
        except Exception as e:
            logger.exception("Failed to process uploaded PDF %s", doc_id)
            meta.update(status="error", error="Something went wrong while processing this PDF.")
            meta["warnings"] = [str(e)]
            meta["steps"] = self._steps()
        self._save_meta(doc_id)

    def list(self): return sorted(self._meta.values(), key=lambda m: m["created"])
    def get(self, doc_id): return self._meta.get(doc_id)

    def _vision_retryable(self, meta: dict) -> bool:
        if "vision_retryable" in meta:
            return bool(meta["vision_retryable"])
        warning = next(
            (item for item in meta.get("warnings", []) if item.startswith("Visual analysis could not run")),
            "",
        )
        return any(phrase in warning for phrase in ("HTTP Error 404", "Connection refused", "Connection reset"))

    def schedule_stale_documents(self) -> list[str]:
        queued = []
        configured_model = os.getenv("OLLAMA_VISION_MODEL", "llava:latest")
        vision_refresh_needed = any(
            meta.get("status") == "ready"
            and (meta.get("vision_model") != configured_model or self._vision_retryable(meta))
            for meta in self._meta.values()
        )
        vision_can_run = vision_refresh_needed and model_available()
        with self._lock:
            for doc_id, meta in self._meta.items():
                abandoned_processing = (
                    meta.get("status") == "processing"
                    and doc_id not in self._processing
                    and doc_id not in self._queued
                )
                stale_parser = meta.get("parser_version", 0) < PARSER_VERSION
                retry_vision = (
                    vision_can_run and meta.get("status") == "ready"
                    and (
                        meta.get("vision_model") != configured_model
                        or self._vision_retryable(meta)
                    )
                )
                if abandoned_processing or (
                    meta.get("status") == "ready" and (stale_parser or retry_vision)
                ):
                    meta.update(
                        status="processing", error=None, progress=10,
                        steps=self._steps(active=1, done=1),
                    )
                    self._queued.add(doc_id)
                    self._save_meta(doc_id)
                    queued.append(doc_id)
        return queued

    def evidence(self, doc_ids) -> list:
        return [e for d in doc_ids if self._meta.get(d, {}).get("status") == "ready" for e in self._evidence[d]]

    def inspect_pages(self, doc_ids: list[str], pages: list[int], limit: int = 6) -> tuple[list, list[str]]:
        targets = [
            (doc_id, page)
            for doc_id in doc_ids
            if (meta := self._meta.get(doc_id)) and meta.get("status") == "ready"
            for page in pages
            if 1 <= page <= meta["pages"]
        ]
        evidence, warnings = [], []
        for doc_id, page_number in targets[:limit]:
            meta = self._meta[doc_id]
            with fitz.open(self._dir(doc_id) / "original.pdf") as pdf:
                page = pdf[page_number - 1]
                try:
                    visuals = analyze_page(page, page_number)
                except VisionError as error:
                    logger.warning(
                        "On-demand visual analysis failed for %s page %s: %s",
                        meta["name"], page_number, error,
                    )
                    warnings.append(
                        f"Visual analysis failed on page {page_number} of {meta['name']}; "
                        "the summary uses OCR and extracted text where available."
                    )
                    continue
            section = next(
                (
                    item.get("section") for item in self._evidence[doc_id]
                    if item["page"] == page_number and item.get("section")
                ),
                None,
            )
            for index, visual in enumerate(visuals, start=1):
                evidence.append({
                    "id": f"{doc_id[:8]}-p{page_number}-ondemand-v{index}",
                    "doc_id": doc_id,
                    "document": meta["name"],
                    "page": page_number,
                    "type": visual["type"],
                    "content": visual["content"],
                    "section": section,
                    "bounding_box": visual["bounding_box"],
                    "confidence": visual["confidence"],
                })

        if len(targets) > limit:
            warnings.append(
                f"Visual analysis was limited to {limit} requested document page(s) for responsiveness; "
                "OCR and extracted text were used for the remaining requested pages."
            )
        return evidence, warnings

    def delete(self, doc_id) -> bool:
        if doc_id not in self._meta:
            return False
        with self._lock:
            self._meta.pop(doc_id); self._evidence.pop(doc_id, None)
        shutil.rmtree(self._dir(doc_id), ignore_errors=True)
        return True

    def page_image(self, doc_id: str, page: int, scale: float) -> Path | None:
        meta = self._meta.get(doc_id)
        if not meta or meta["status"] != "ready" or not 1 <= page <= meta["pages"]:
            return None
        scale = max(0.2, min(scale, 3.0))
        out = self._dir(doc_id) / "pages" / f"{page}_{scale:.2f}.png"
        if not out.exists():
            out.parent.mkdir(exist_ok=True)
            with fitz.open(self._dir(doc_id) / "original.pdf") as pdf:
                pdf[page - 1].get_pixmap(matrix=fitz.Matrix(scale, scale)).save(out)
        return out
