"""Builds the source list shown under an answer from the verified claims."""

from verifier import find_quote_match

TYPE_LABEL = {
    "text": "Text",
    "table": "Table",
    "chart": "Chart",
    "diagram": "Diagram",
    "image": "Image",
    "ocr": "OCR text",
}


def build_sources(claims: list, ev_by_id: dict) -> list:
    seen, out = set(), []
    for c in claims:
        quote = c.get("quote", "")
        for eid in c.get("evidence_ids", []):
            e = ev_by_id.get(eid)
            if not e or eid in seen:
                continue
            matched_quote = find_quote_match(
                quote,
                e["content"],
                allow_ocr=e.get("type") == "ocr",
            ) if quote else None
            if quote and not matched_quote:
                continue
            seen.add(eid)
            label = TYPE_LABEL.get(e["type"], "Text")
            out.append({
                "evidence_id": eid, "doc_id": e["doc_id"], "document": e["document"],
                "page": e["page"], "type": e["type"], "section": e.get("section"),
                "label": f"{label}" + (f" · {e['section']}" if e.get("section") else ""),
                "snippet": (matched_quote or e["content"])[:220],
                "bbox": e.get("bounding_box"), "confidence": e.get("confidence", 1.0),
            })
    return out
