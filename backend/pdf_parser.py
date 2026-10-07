"""Extract text, OCR, tables, and locally analyzed visual evidence from PDFs."""
import re
import logging
import subprocess
import statistics
from dataclasses import dataclass

import fitz  # PyMuPDF

from vision_processor import VisionError, analyze_page

MIN_TEXT_CHARS = 25
MAX_CHUNK_CHARS = 900
PARSER_VERSION = 9
MAX_VISION_PAGES = 4
logger = logging.getLogger(__name__)


class PDFError(Exception):
    """Raised with a user-friendly message."""


@dataclass
class ParseResult:
    pages: int
    evidence: list
    warnings: list


def _evenly_spaced(items: list[int], limit: int) -> list[int]:
    if len(items) <= limit:
        return items
    if limit <= 1:
        return [items[0]]
    indexes = [round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)]
    return [items[index] for index in indexes]


def _select_vision_pages(page_assets: list[dict], limit: int = MAX_VISION_PAGES) -> set[int]:
    candidates = [i for i, assets in enumerate(page_assets) if assets["has_visual"]]
    vector_only = [
        i for i in candidates
        if page_assets[i]["vector_visual"] and not page_assets[i]["images"]
    ]
    selected = _evenly_spaced(vector_only, min(len(vector_only), limit // 2))
    remaining = limit - len(selected)
    other_candidates = [i for i in candidates if i not in selected]
    selected.extend(_evenly_spaced(other_candidates, remaining))
    return set(selected)


def open_pdf(path) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception:
        raise PDFError("This file couldn't be opened. It may be corrupted or not a real PDF.")
    if doc.needs_pass:
        raise PDFError("This PDF is password-protected. Remove the password and upload it again.")
    if doc.page_count == 0:
        raise PDFError("This PDF has no pages.")
    return doc


def _block_text(block) -> tuple[str, float]:
    parts, sizes = [], []
    for line in block.get("lines", []):
        spans = [s for s in line["spans"] if s["text"].strip()]
        if spans:
            parts.append(" ".join(s["text"].strip() for s in spans))
            sizes.extend(s["size"] for s in spans)
    return " ".join(parts).strip(), (max(sizes) if sizes else 0.0)


def _ocr_image(page, rect) -> str:
    scale = min(4.0, 3200 / max(rect.width, rect.height))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect)
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "6"],
        input=pixmap.tobytes("png"),
        capture_output=True,
        check=True,
        timeout=30,
    )
    return result.stdout.decode("utf-8", errors="replace").strip()


def _normalize_stacked_fractions(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    formulas = []
    for i in range(1, len(lines) - 1):
        match = re.fullmatch(r"([A-Za-z][A-Za-z ]*?)\s*=\s*[_=|.\-—–−]{2,}", lines[i])
        if not match:
            continue
        numerator = re.sub(r"^[^A-Za-z0-9]+", "", lines[i - 1]).strip()
        denominator = re.sub(r"^[^A-Za-z0-9]+", "", lines[i + 1]).strip()
        fragment = r"[A-Za-z0-9][A-Za-z0-9\s.+*/()%-]*"
        if re.fullmatch(fragment, numerator) and re.fullmatch(fragment, denominator):
            formulas.append(f"Formula layout reconstructed from OCR: {match[1].strip()} = {numerator} / ({denominator})")
    return formulas


def _image_rectangles(page) -> list:
    rectangles, seen = [], set()
    for image in page.get_images(full=True):
        for rect in page.get_image_rects(image[0]):
            key = tuple(round(value, 2) for value in rect)
            if key not in seen:
                rectangles.append(rect)
                seen.add(key)
    return rectangles


def parse_pdf(path, doc_id: str, doc_name: str, on_progress=None) -> ParseResult:
    doc = open_pdf(path)
    n = doc.page_count
    pages_blocks, all_sizes, warnings, page_assets = [], [], [], []

    for i in range(n):
        page = doc[i]
        w, h = page.rect.width, page.rect.height
        images = _image_rectangles(page)
        drawings = page.get_drawings()
        vector_visual = len(drawings) >= 8
        page_assets.append({
            "images": images,
            "drawing_count": len(drawings),
            "vector_visual": vector_visual,
            "has_visual": bool(images) or vector_visual,
        })
        if on_progress:
            on_progress("page_detection", i + 1, n)

    vision_pages = _select_vision_pages(page_assets)
    visual_page_count = sum(asset["has_visual"] for asset in page_assets)
    if visual_page_count > len(vision_pages):
        warnings.append(
            f"Visual analysis sampled {len(vision_pages)} of {visual_page_count} visual pages to "
            "keep processing responsive; text and OCR were processed across all pages."
        )

    vision_failures = []
    ocr_pages = []
    for i, page in enumerate(doc):
        w, h = page.rect.width, page.rect.height
        blocks = []
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            text, size = _block_text(b)
            if not text:
                continue
            x0, y0, x1, y1 = b["bbox"]
            blocks.append((text, size, [x0 / w, y0 / h, x1 / w, y1 / h], "text"))
            all_sizes.append(size)
        native_chars = sum(len(b[0]) for b in blocks)
        image_rects = page_assets[i]["images"]
        if native_chars < MIN_TEXT_CHARS and not image_rects:
            image_rects.append(page.rect)
        ocr_failed = False
        for rect in image_rects:
            try:
                text = _ocr_image(page, rect)
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                ocr_failed = True
                continue
            if text:
                x0, y0, x1, y1 = rect
                formulas = _normalize_stacked_fractions(text)
                content = "\n".join([*formulas, f"OCR text:\n{text}"])
                blocks.append((content, 11.0, [x0 / w, y0 / h, x1 / w, y1 / h], "ocr"))
        if ocr_failed:
            warnings.append(
                f"Page {i + 1} contains image or scanned content that OCR could not read. "
                "Check that Tesseract OCR is installed and working."
            )
        if any(b[3] == "ocr" for b in blocks):
            ocr_pages.append(i + 1)
        elif native_chars < MIN_TEXT_CHARS and not ocr_failed:
            warnings.append(f"Page {i + 1} has little or no readable text; OCR found no text.")
        blocks.sort(key=lambda b: (b[2][1], b[2][0]))
        pages_blocks.append(blocks)
        if on_progress:
            on_progress("text_extraction", i + 1, n)

    if ocr_pages:
        warnings.append(
            f"OCR text was extracted from {len(ocr_pages)} page(s); verify formulas and symbols against the pages."
        )

    for i, page in enumerate(doc):
        w, h = page.rect.width, page.rect.height
        if page_assets[i]["drawing_count"] >= 8:
            try:
                tables = page.find_tables().tables
            except Exception as error:
                warnings.append(f"Page {i + 1} table detection failed: {error}")
                tables = []
        else:
            tables = []
        for table_index, table in enumerate(tables, start=1):
            rows = table.extract()
            normalized_rows = [
                [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row]
                for row in rows
            ]
            normalized_rows = [row for row in normalized_rows if any(row)]
            if not normalized_rows:
                continue
            lines = [f"Table {table_index}"]
            lines.extend(" | ".join(row) for row in normalized_rows)
            x0, y0, x1, y1 = table.bbox
            pages_blocks[i].append((
                "\n".join(lines), 11.0, [x0 / w, y0 / h, x1 / w, y1 / h], "table",
            ))

        if i in vision_pages:
            try:
                visuals = analyze_page(page, i + 1, has_native_table=bool(tables))
            except VisionError as error:
                vision_failures.append((i + 1, str(error)))
            else:
                for visual in visuals:
                    pages_blocks[i].append((
                        visual["content"], 11.0, visual["bounding_box"], visual["type"],
                    ))
                if visuals:
                    warnings.append(
                        f"Page {i + 1} includes local vision-model descriptions; verify chart values against the page."
                    )
        if on_progress:
            on_progress("visual_analysis", i + 1, n)
    if vision_failures:
        failed_pages = ", ".join(str(page_number) for page_number, _ in vision_failures)
        detail = vision_failures[0][1].split(": ", 1)[-1]
        warning = (
            f"Visual analysis could not run on pages {failed_pages}. "
            f"Check Ollama and the configured OLLAMA_VISION_MODEL. Details: {detail}"
        )
        logger.warning(warning)
        warnings.append(warning)

    body = statistics.median(all_sizes) if all_sizes else 11.0
    evidence, section = [], None

    for pno, blocks in enumerate(pages_blocks, start=1):
        chars = sum(len(b[0]) for b in blocks)
        if chars < MIN_TEXT_CHARS:
            continue
        buf, buf_box, buf_type, idx = [], None, None, 0

        def flush():
            nonlocal buf, buf_box, buf_type, idx
            if buf:
                idx += 1
                evidence.append({
                    "id": f"{doc_id[:8]}-p{pno}-t{idx}", "doc_id": doc_id, "document": doc_name,
                    "page": pno, "type": buf_type, "section": section,
                    "content": " ".join(buf), "bounding_box": buf_box,
                    "confidence": {"ocr": 0.8, "chart": 0.7, "image": 0.7, "diagram": 0.7, "table": 0.95}.get(buf_type, 1.0),
                })
            buf, buf_box, buf_type = [], None, None

        for text, size, box, source_type in blocks:
            if source_type in {"ocr", "table", "chart", "image", "diagram"}:
                flush()
                buf.append(text)
                buf_box, buf_type = box, source_type
                flush()
                continue
            if buf and source_type != buf_type:
                flush()
            if source_type == "text" and size >= body * 1.2 and len(text) < 120:
                flush()
                section = re.sub(r"\s+", " ", text)
                continue
            if sum(len(t) for t in buf) + len(text) > MAX_CHUNK_CHARS:
                flush()
            buf.append(text)
            buf_type = source_type
            buf_box = box if buf_box is None else [
                min(buf_box[0], box[0]), min(buf_box[1], box[1]),
                max(buf_box[2], box[2]), max(buf_box[3], box[3])]
        flush()

    if not evidence:
        warnings.append("No readable text was found in this document.")
    return ParseResult(pages=n, evidence=evidence, warnings=warnings)
