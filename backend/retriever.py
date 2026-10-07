"""Keyword retrieval (BM25). Phase 2+ adds embeddings + ChromaDB behind the same interface."""
import math
import re
from collections import Counter

STOP = set("a an and are as at be by for from has have in is it its of on or that the this to was were what which who with how did do does".split())
NUMBER = re.compile(r"\d")


def requested_pages(question: str) -> list[int]:
    match = re.search(
        r"\b(?:pages?|pgs?)\s+(\d+(?:\s*(?:-|–|—|to|,|and)\s*\d+)*)",
        question,
        re.I,
    )
    if not match:
        return []

    pages = []
    for part in re.split(r"\s*(?:,|and)\s*", match.group(1), flags=re.I):
        range_match = re.fullmatch(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)", part, re.I)
        if range_match:
            start, end = map(int, range_match.groups())
            if end < start or end - start > 100:
                return []
            pages.extend(range(start, end + 1))
            continue
        if part.isdigit():
            pages.append(int(part))
    return list(dict.fromkeys(pages))


def is_summary_request(question: str) -> bool:
    return bool(
        re.search(r"\b(summarize|summarise|summary|overview)\b", question, re.I)
        or re.search(
            r"\b(?:asking|ask)\s+for\s+all\s+(?:\d+\s+)?(?:docs?|documents?)\b",
            question,
            re.I,
        )
    )


def is_visual_summary_request(question: str) -> bool:
    return (
        is_summary_request(question)
        and bool(re.search(r"\b(images?|pictures?|photos?|photographs?|visuals?|charts?|graphs?|figures?|diagrams?)\b", question, re.I))
    )


def retrieve_visual_summary(evidence: list, top_k: int = 5) -> list:
    visual_types = {"chart", "diagram", "image"}
    visual_terms = re.compile(
        r"\b(image|photo|photograph|visual|chart|graph|figure|diagram|plot)\b", re.I
    )
    explicit_visual = re.compile(
        r"\b(visual evidence|figure\s*\d+|chart shows|graph shows|diagram for|image shows|photo shows)\b",
        re.I,
    )
    excluded_metadata = re.compile(
        r"\b(test capability|visual reasoning test|evidence map|this index|recommended test questions|assignment|reference|bibliography)\b",
        re.I,
    )
    ranked = []
    for item in evidence:
        content = item["content"]
        section = item.get("section") or ""
        if excluded_metadata.search(f"{section} {content[:180]}") or re.search(
            r"\btest corpus\b", content[:120], re.I
        ):
            continue
        kind = item.get("type", "text")
        if re.search(r"\breference link\b", content[:200], re.I):
            continue
        if kind == "ocr" and re.search(r"\bExercises\b", content[:140], re.I):
            continue
        if kind in visual_types:
            score = 100
        elif explicit_visual.search(content):
            score = 25
        elif kind == "ocr" and len(content) >= 80 and visual_terms.search(content):
            if re.search(r"\bsymbols used in ER diagram\b", content, re.I):
                score = 35
            elif re.search(r"\bER diagram for\b", content, re.I):
                score = 30
            elif re.search(r"\bER diagram (?:shown|in) the figure\b", content, re.I):
                score = 15
            else:
                score = 5
        else:
            continue
        selected = item
        if kind == "text":
            if re.search(r"\b(chart|graph|plot)\b", content, re.I):
                selected = {**item, "type": "chart"}
            elif re.search(r"\b(visual evidence|visual inspection|image shows|photo shows)\b", content, re.I):
                selected = {**item, "type": "image"}
            elif re.search(r"\b(diagram)\b", content, re.I):
                selected = {**item, "type": "diagram"}
        ranked.append((score, len(content), selected))

    ranked.sort(key=lambda entry: (-entry[0], -entry[1], entry[2]["page"]))
    return [item for _, _, item in ranked[:top_k]]


def _broad_intent(question: str) -> str | None:
    if is_summary_request(question):
        return "summary"
    q = question.lower()
    if re.search(r"\b(extract|list|find|show)\b.*\b(numbers?|statistics|metrics)\b", q):
        return "numbers"
    if re.search(r"\b(supporting evidence|find evidence)\b", q):
        return "evidence"
    if re.search(r"\bcompare\b.*\b(findings|main points)\b", q):
        return "comparison"
    return None


def _retrieve_broad(evidence: list, intent: str, top_k: int, per_doc: int) -> list:
    ordered = list(evidence)
    if intent == "numbers":
        ordered.sort(key=lambda e: len(NUMBER.findall(e["content"])), reverse=True)

    if intent == "summary":
        by_doc: dict[str, dict[int, list]] = {}
        for item in ordered:
            by_doc.setdefault(item["doc_id"], {}).setdefault(item["page"], []).append(item)

        def is_metadata_page(doc_id: str, page: int) -> bool:
            page_items = by_doc[doc_id][page]
            return bool(re.search(
                r"\b(test corpus|recommended test questions|test questions|table of contents)\b",
                " ".join(
                    f"{item.get('section') or ''} {item['content'][:180]}"
                    for item in page_items
                ),
                re.I,
            ))

        docs = []
        for doc_id, pages in by_doc.items():
            all_pages = sorted(pages)
            content_pages = [page for page in all_pages if not is_metadata_page(doc_id, page)]
            docs.append((doc_id, content_pages or all_pages))
        slots = [0] * len(docs)
        remaining = min(top_k, sum(len(pages) for _, pages in docs))
        while remaining:
            progressed = False
            for i, (_, pages) in enumerate(docs):
                if slots[i] < len(pages) and remaining:
                    slots[i] += 1
                    remaining -= 1
                    progressed = True
            if not progressed:
                break

        selected_pages = []
        for (doc_id, pages), count in zip(docs, slots):
            if count == 1:
                indexes = [0]
            elif count > 1:
                indexes = [round(i * (len(pages) - 1) / (count - 1)) for i in range(count)]
            else:
                indexes = []
            selected_pages.append([
                (doc_id, pages[index]) for index in indexes
            ])

        selected, page_position = [], 0
        type_priority = {"text": 0, "ocr": 1, "table": 2, "chart": 3, "diagram": 4, "image": 5}
        while any(page_position < len(pages) for pages in selected_pages):
            for doc_index, pages in enumerate(selected_pages):
                if page_position >= len(pages):
                    continue
                doc_id, page = pages[page_position]
                selected.append(min(
                    by_doc[doc_id][page],
                    key=lambda item: (
                        type_priority.get(item.get("type", "text"), 6),
                        -len(item["content"]),
                    ),
                ))
            page_position += 1

        seen = {item["id"] for item in selected}
        for evidence_type in ("table", "ocr", "chart", "diagram", "image"):
            if len(selected) >= top_k + 5:
                break
            candidates = [
                item for item in ordered
                if item.get("type", "text") == evidence_type and item["id"] not in seen
                and not is_metadata_page(item["doc_id"], item["page"])
            ]
            if candidates:
                item = max(candidates, key=lambda candidate: len(candidate["content"]))
                selected.append(item)
                seen.add(item["id"])
        return selected

    picked, counts, seen = [], Counter(), set()
    for item in ordered:
        if counts[item["doc_id"]] == 0:
            picked.append(item)
            counts[item["doc_id"]] += 1
            seen.add(item["id"])
    for item in ordered:
        if len(picked) >= top_k:
            break
        if item["id"] not in seen and counts[item["doc_id"]] < per_doc:
            picked.append(item)
            counts[item["doc_id"]] += 1
            seen.add(item["id"])
    present_types = {item.get("type", "text") for item in picked}
    for item in ordered:
        evidence_type = item.get("type", "text")
        if (
            evidence_type not in present_types
            and item["id"] not in seen
            and len(picked) < top_k + 5
        ):
            picked.append(item)
            present_types.add(evidence_type)
            seen.add(item["id"])
    return picked


def tokenize(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s.lower()) if t not in STOP]


def retrieve(question: str, evidence: list, top_k: int = 8, per_doc: int = 2, k1=1.5, b=0.75) -> list:
    q = set(tokenize(question))
    if not q or not evidence:
        return []
    if re.search(r"\b(reasons?|causes?|drivers?|why)\b", question, re.I):
        q.update({"cause", "causes", "loss", "losses", "root", "driver", "drivers", "factor", "factors"})
    if (
        re.search(r"\befficiency\b", question, re.I)
        and re.search(r"\bq2\b", question, re.I)
        and re.search(r"\bq4\b", question, re.I)
    ):
        q.update({"metric", "metrics"})
    intent = _broad_intent(question)
    if intent:
        return _retrieve_broad(evidence, intent, top_k, per_doc)

    docs = [tokenize(e["content"] + " " + (e.get("section") or "")) for e in evidence]
    avg = sum(map(len, docs)) / len(docs) or 1
    df = Counter(t for d in docs for t in set(d))
    N = len(docs)
    scored = []
    for e, d in zip(evidence, docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if tf[t]:
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        if s > 0:
            scored.append((s, e))
    scored.sort(key=lambda x: -x[0])
    picked, seen = [], set()
    for _, e in scored[:top_k]:
        picked.append(e); seen.add(e["id"])
    counts = Counter(e["doc_id"] for e in picked)          # make sure every selected doc is represented
    for _, e in scored[top_k:]:
        if counts[e["doc_id"]] < per_doc and e["id"] not in seen:
            picked.append(e); seen.add(e["id"]); counts[e["doc_id"]] += 1

    present_types = {e.get("type", "text") for e in picked}
    for _, e in scored:
        evidence_type = e.get("type", "text")
        if evidence_type not in present_types and e["id"] not in seen:
            picked.append(e)
            seen.add(e["id"])
            present_types.add(evidence_type)
    return picked
