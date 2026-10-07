"""Evidence-grounded answering: LLM drafts, Python calculates, verifier checks. Refuses when unsupported."""
import json
import logging
import os
import re

from anthropic import Anthropic

from calculator import calculate
from citations import build_sources
from retriever import (
    is_summary_request,
    is_visual_summary_request,
    requested_pages,
    retrieve,
    retrieve_visual_summary,
)
from verifier import verify

MODEL = os.getenv("OLLAMA_MODEL", "llama3:instruct")
logger = logging.getLogger(__name__)
REFUSAL = ("I cannot determine this from the provided documents.\n\n"
           "No supporting information was found in the available evidence.")
UNRELIABLE = "I cannot reliably determine this from the available evidence."

SYSTEM = """You answer questions using ONLY the numbered evidence passages provided. Rules:
- Never use outside knowledge. If the evidence does not answer the question, set can_answer to false.
- OCR evidence may include a formula reconstructed from the positions of a stacked numerator and denominator; use it as image-derived evidence when relevant.
- Evidence may include extracted tables and local vision descriptions of charts, diagrams, and images. Combine relevant evidence across these types when answering comparisons, and do not claim visual values that the cited evidence does not report.
- Never do arithmetic yourself. For any calculation, add an entry to "calculations" with an expression made only of numbers copied from the evidence, and reference its result in the answer as {{calc:0}}, {{calc:1}}, ...
- Every factual statement must appear in "claims" with the evidence ids that support it and a "quote": a short verbatim excerpt (max 200 characters) copied exactly from one of those passages.
- Write a direct answer_markdown of 1-3 concise sentences. The interface displays document names and page numbers separately.
Reply with a single JSON object and nothing else:
{"can_answer": bool, "answer_markdown": str,
 "claims": [{"text": str, "evidence_ids": [str], "quote": str}],
 "calculations": [{"label": str, "expression": str, "evidence_ids": [str]}],
 "confidence": "high"|"medium"|"low"}"""


def _client():
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    return Anthropic(api_key="ollama", base_url=base_url)


def _format_evidence(evidence):
    blocks = []
    for e in evidence:
        sec = f" | section: {e['section']}" if e.get("section") else ""
        blocks.append(f"[{e['id']}] {e['document']} | page {e['page']}{sec} | type: {e['type']}\n{e['content']}")
    return "\n\n".join(blocks)


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    payload = text[text.index("{"): text.rindex("}") + 1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        escaped = []
        in_string = False
        is_escaped = False
        replacements = {"\n": r"\n", "\r": r"\r", "\t": r"\t"}
        for index, char in enumerate(payload):
            if in_string and char == "\\" and not is_escaped:
                next_char = payload[index + 1] if index + 1 < len(payload) else ""
                valid_escape = next_char in '"\\/bfnrt'
                valid_unicode_escape = (
                    next_char == "u"
                    and index + 5 < len(payload)
                    and all(c in "0123456789abcdefABCDEF" for c in payload[index + 2:index + 6])
                )
                if not (valid_escape or valid_unicode_escape):
                    escaped.append(r"\\")
                    continue
            if in_string and not is_escaped and ord(char) < 0x20:
                escaped.append(replacements.get(char, f"\\u{ord(char):04x}"))
                continue
            escaped.append(char)
            if in_string and is_escaped:
                is_escaped = False
            elif char == "\\" and in_string:
                is_escaped = True
            elif char == '"':
                in_string = not in_string
        return json.loads("".join(escaped))


def _fmt(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _combine_document_summaries(results: list[dict], unavailable: list[tuple[str, str]] | None = None) -> dict:
    sources, seen = [], set()
    sections, checks, calculations = [], [], []
    confidence_rank = {"Low": 0, "Medium": 1, "High": 2}
    confidence = "High"
    for result in results:
        document = result["sources"][0]["document"]
        sections.append(f"**{document}**\n{result['answer']}")
        for source in result["sources"]:
            if source["evidence_id"] not in seen:
                sources.append(source)
                seen.add(source["evidence_id"])
        checks.extend(f"{document}: {check}" for check in result["checks"])
        calculations.extend(result["calculations"])
        if confidence_rank.get(result["confidence"], 0) < confidence_rank[confidence]:
            confidence = result["confidence"]
    for document, reason in unavailable or []:
        sections.append(f"**{document}**\n{reason}")
    return {
        "status": "answered",
        "answer": "\n\n".join(sections),
        "sources": sources,
        "confidence": confidence,
        "checks": checks,
        "calculations": calculations,
    }


def _extractive_document_summary(evidence: list) -> dict:
    usable = [
        item for item in evidence
        if item.get("type") in {"text", "table", "chart", "diagram", "image", "ocr"}
        and item.get("content", "").strip()
    ]
    usable.sort(
        key=lambda item: (
            {"table": 0, "chart": 1, "image": 2, "diagram": 3, "text": 4, "ocr": 5}.get(
                item.get("type"), 6
            ),
            -len(item["content"]),
            item["page"],
        )
    )
    selected = usable[:3]
    if not selected:
        return {
            "status": "insufficient",
            "answer": "No readable text or visual description was extracted from this PDF.",
            "sources": [],
            "confidence": "Low",
            "checks": [],
            "calculations": [],
        }

    claims, lines = [], []
    for item in selected:
        excerpt = re.sub(r"^OCR text:\s*", "", item["content"].strip(), flags=re.I)
        excerpt = excerpt[:200].rsplit(" ", 1)[0] if len(excerpt) > 200 else excerpt
        if not excerpt:
            continue
        claim = {
            "text": f"Page {item['page']} extracted passage: {excerpt}",
            "evidence_ids": [item["id"]],
            "quote": excerpt,
        }
        claims.append(claim)
        lines.append(f"- Page {item['page']} ({item['type']}): “{excerpt}”")

    evidence_by_id = {item["id"]: item for item in selected}
    sources = build_sources(claims, evidence_by_id)
    if not sources:
        return {
            "status": "insufficient",
            "answer": "Readable passages were extracted, but they could not be matched to source pages.",
            "sources": [],
            "confidence": "Low",
            "checks": [],
            "calculations": [],
        }
    return {
        "status": "answered",
        "answer": (
            "The model summary could not be verified, so these are direct extracts "
            "from the document rather than a generated summary:\n" + "\n".join(lines)
        ),
        "sources": sources,
        "confidence": "Low",
        "checks": ["Showing exact extracted passages because the generated summary could not be verified."],
        "calculations": [],
    }


def _answer_visual_summary(evidence: list) -> dict:
    ev_by_id = {item["id"]: item for item in evidence}
    claims, lines = [], []
    for item in evidence:
        content = item["content"]
        marker = re.search(
            r"\b(visual evidence|chart shows|graph shows|figure\s*\d+|image shows|photo shows|"
            r"symbols used in ER diagram|ER diagram for|ER diagram shown)\b",
            content,
            re.I,
        )
        excerpt = content[marker.start():] if marker else content
        excerpt = excerpt.strip()
        if len(excerpt) > 200:
            excerpt = excerpt[:200].rsplit(" ", 1)[0]
        kind = item.get("type", "visual").capitalize()
        claims.append({
            "text": f"{kind} evidence: {excerpt}",
            "evidence_ids": [item["id"]],
            "quote": excerpt,
        })
        lines.append(f"**{kind} · page {item['page']}:** {excerpt}")

    answer = "\n\n".join(lines)
    result = {"answer_markdown": answer, "claims": claims}
    problems = verify(result, ev_by_id)
    if problems:
        logger.error("Extracted visual summary failed evidence verification: %s", problems)
        return {
            "status": "insufficient",
            "answer": "The extracted visual descriptions could not be verified against their source pages.",
            "sources": [],
            "confidence": "Low",
            "checks": [],
            "calculations": [],
        }
    return {
        "status": "answered",
        "answer": answer,
        "sources": build_sources(claims, ev_by_id),
        "confidence": "Medium",
        "checks": [f"{len(claims)} visual passage(s) quoted from the cited pages"],
        "calculations": [],
    }


def _clean_extracted_text(evidence: list) -> str:
    lines = []
    for item in evidence:
        if "-ondemand-" in item["id"]:
            continue
        content = re.sub(r"^OCR text:\s*", "", item["content"], flags=re.I)
        for raw_line in content.splitlines():
            line = re.sub(r"^[^\w]+", "", raw_line, flags=re.UNICODE)
            line = re.sub(r"[^\w\s.,:;!?%()+/&'-]", " ", line, flags=re.UNICODE)
            line = re.sub(r"\s+", " ", line).strip(" _|")
            words = re.findall(r"[A-Za-z]{2,}", line)
            if len(words) >= 2:
                lines.append(line)
    return " ".join(dict.fromkeys(lines))


def _answer_page_summaries(question: str, evidence: list, pages: list[int], route: dict) -> dict:
    grouped: dict[tuple[str, int], list] = {}
    for item in evidence:
        grouped.setdefault((item["doc_id"], item["page"]), []).append(item)

    summaries, sources, checks = [], [], []
    missing_pages = sorted(set(pages) - {page for _, page in grouped})
    confidence_rank = {"Low": 0, "Medium": 1, "High": 2}
    confidence = "High"
    client = _client()
    for (doc_id, page), page_evidence in grouped.items():
        document = page_evidence[0]["document"]
        active_evidence = page_evidence
        result = None
        used_ocr_fallback = False
        for attempt in range(2):
            ev_by_id = {item["id"]: item for item in active_evidence}
            prompt = (
                f"Question type hints: {json.dumps(route)}\n\n"
                f"EVIDENCE\n{_format_evidence(active_evidence)}\n\n"
                f"QUESTION\n{question}\n\n"
                f"Summarize only PDF page {page} above in one or two concise plain-text sentences. "
                "Do not add facts, terms, or conclusions that are not explicitly supported by this page. "
                "Preserve distinctions between cases. For each factual statement, provide the exact "
                "evidence id shown above and a short quote copied from that passage. Do not use ellipses. "
                "Every sentence in answer_markdown must correspond to a claim, and include every claim "
                "in the final summary."
            )
            messages = [{"role": "user", "content": prompt}]
            response = client.messages.create(
                model=MODEL,
                max_tokens=700,
                system=SYSTEM,
                messages=messages,
                extra_body={"temperature": 0},
            )
            raw = response.content[0].text
            try:
                candidate = _parse(raw)
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                problems = [f"Reply was not valid JSON: {error}"]
            else:
                problems = verify(candidate, ev_by_id)
                if candidate.get("can_answer") and not problems:
                    result = candidate
                    break
                if not candidate.get("can_answer"):
                    problems = ["The page summary was declined."]
            if attempt == 0:
                text_evidence = [
                    item for item in page_evidence
                    if item.get("type") not in {"image", "chart", "diagram"}
                    and "-ondemand-" not in item["id"]
                ]
                if text_evidence and len(text_evidence) < len(page_evidence):
                    active_evidence = text_evidence
                    used_ocr_fallback = True
                else:
                    messages.extend([
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": (
                            "Correct the page summary using only this page. "
                            + "; ".join(problems)
                            + " Return JSON only, with exact source quotes and evidence ids."
                        )},
                    ])
                    continue

        if result is None:
            fallback_evidence = [
                item for item in page_evidence
                if item.get("type") in {"ocr", "text", "table"}
            ]
            extracted_text = _clean_extracted_text(fallback_evidence)
            if extracted_text:
                fallback_claims = [{
                    "text": f"OCR text extracted from page {page}.",
                    "evidence_ids": [item["id"]],
                    "quote": item["content"][:180],
                } for item in fallback_evidence]
                summaries.append(
                    f"**{document} · page {page}**\n"
                    f"Extracted text (OCR; summary could not be verified): {extracted_text}"
                )
                sources.extend(build_sources(fallback_claims, {item["id"]: item for item in fallback_evidence}))
                checks.append(
                    f"{document} page {page}: summary could not be verified; showing extracted OCR/text instead"
                )
            else:
                summaries.append(
                    f"**{document} · page {page}**\n"
                    "This page could not be summarized reliably from the extracted text."
                )
            confidence = "Low"
            continue

        answer = "\n".join(
            str(claim.get("text") or "").strip()
            for claim in result.get("claims") or []
            if str(claim.get("text") or "").strip()
        )
        if not answer:
            summaries.append(f"**{document} · page {page}**\nThis page could not be summarized reliably from the extracted text.")
            confidence = "Low"
            continue

        summaries.append(f"**{document} · page {page}**\n{answer}")
        sources.extend(build_sources(result["claims"], ev_by_id))
        checks.append(f"{document} page {page}: {len(result['claims'])} claim(s) matched to quoted text")
        if used_ocr_fallback:
            checks.append(
                f"{document} page {page}: summary used OCR/text because visual evidence did not verify"
            )
        page_confidence = str(result.get("confidence", "medium")).capitalize()
        if confidence_rank.get(page_confidence, 0) < confidence_rank[confidence]:
            confidence = page_confidence

    if missing_pages:
        summaries.append(
            f"**Pages not found:** {', '.join(map(str, missing_pages))} "
            "had no extracted evidence in the selected PDFs."
        )
    if not sources:
        return {
            "status": "insufficient",
            "answer": "\n\n".join(summaries) or "No selected document contains evidence for the requested pages.",
            "sources": [],
            "confidence": "Low",
            "checks": [],
            "calculations": [],
        }
    return {
        "status": "answered",
        "answer": "\n\n".join(summaries),
        "sources": sources,
        "confidence": confidence,
        "checks": checks,
        "calculations": [],
    }


def answer_question(question: str, evidence: list, route: dict) -> dict:
    pages = requested_pages(question)
    is_page_summary = bool(pages)
    is_summary = is_summary_request(question) or is_page_summary
    is_visual_summary = is_visual_summary_request(question)
    if not evidence:
        answer = (
            "No image, chart, figure, or diagram evidence was extracted from the selected PDFs."
            if is_visual_summary else REFUSAL
        )
        return {"status": "insufficient", "answer": answer, "sources": [], "confidence": "Low", "checks": [], "calculations": []}
    if is_page_summary:
        requested = set(pages)
        evidence = [item for item in evidence if item["page"] in requested]
        if not evidence:
            page_list = ", ".join(map(str, pages))
            return {
                "status": "insufficient",
                "answer": f"None of the selected documents contain readable evidence on page(s) {page_list}.",
                "sources": [],
                "confidence": "Low",
                "checks": [],
                "calculations": [],
            }
        return _answer_page_summaries(question, evidence, pages, route)
    if is_summary:
        documents: dict[str, list] = {}
        for item in evidence:
            documents.setdefault(item["doc_id"], []).append(item)
        if not is_page_summary and route.get("multi_document") and len(documents) > 1:
            results = []
            unavailable = []
            for items in documents.values():
                document = items[0]["document"]
                doc_evidence = (
                    retrieve_visual_summary(items) if is_visual_summary
                    else retrieve(question, items)
                )
                if not doc_evidence:
                    unavailable.append((
                        document,
                        "No image, chart, figure, or diagram evidence was extracted from this PDF.",
                    ))
                    continue
                result = answer_question(
                    question, doc_evidence, {**route, "multi_document": False}
                )
                if result["status"] != "answered":
                    if is_visual_summary:
                        unavailable.append((
                            document,
                            "Visual evidence was found, but its summary could not be verified.",
                        ))
                        continue
                    result = _extractive_document_summary(doc_evidence)
                    if result["status"] != "answered":
                        unavailable.append((document, result["answer"]))
                        continue
                results.append(result)
            if is_visual_summary:
                if not results:
                    return {
                        "status": "insufficient",
                        "answer": "No image, chart, figure, or diagram evidence could be summarized from the selected PDFs.",
                        "sources": [],
                        "confidence": "Low",
                        "checks": [],
                        "calculations": [],
                    }
                return _combine_document_summaries(results, unavailable)
            return _combine_document_summaries(results)
        if not is_page_summary:
            evidence = (
                retrieve_visual_summary(evidence) if is_visual_summary
                else retrieve(question, evidence)
            )
        if not evidence:
            answer = (
                "No image, chart, figure, or diagram evidence was extracted from this PDF."
                if is_visual_summary else REFUSAL
            )
            return {"status": "insufficient", "answer": answer, "sources": [], "confidence": "Low", "checks": [], "calculations": []}
        if is_visual_summary:
            return _answer_visual_summary(evidence)

    ev_by_id = {e["id"]: e for e in evidence}
    client = _client()
    summary_guidance = ""
    if is_summary:
        summary_guidance = (
            "\nSummary request: Summarize substantive findings from the evidence, including key results "
            "and numbers where available. Do not summarize a cover page, test checklist, or document "
            "description instead of its findings."
        )
        summary_guidance += "\n"
    if is_page_summary:
        summary_guidance += (
            f"\nPage-specific summary request: Summarize only the provided evidence from PDF page(s) "
            f"{', '.join(map(str, pages))}. Return a concise plain-text summary in answer_markdown "
            "with no code fence. Include the content of every requested page that has evidence. "
            "Do not summarize other pages or describe the evidence list. OCR passages may contain "
            "recognition mistakes; do not silently correct them. For each concise factual claim, copy "
            "a short exact substring from the cited page as its quote; never use ellipses or invented text.\n"
            "Keep every statement close to what the source explicitly says; do not add causes, examples, "
            "or terminology that is not in the quoted passage. Preserve distinctions between separate "
            "conditions or cases; do not merge their rules. Prefer one concise sentence per requested page.\n"
        )
    prompt = (
        f"Question type hints: {json.dumps(route)}\n"
        f"{summary_guidance}\nEVIDENCE\n{_format_evidence(evidence)}\n\nQUESTION\n{question}"
    )
    messages = [{"role": "user", "content": prompt}]
    retried = False

    for attempt in range(2):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1800,
            system=SYSTEM,
            messages=messages,
            extra_body={"temperature": 0},
        )
        raw = resp.content[0].text
        try:
            result = _parse(raw)
        except Exception as error:
            logger.warning("Ollama reply was not valid JSON: %s", error)
            problems = ["Reply was not valid JSON."]
            result = None
        else:
            if not result.get("can_answer"):
                logger.warning("Ollama model declined the question.")
                return {"status": "insufficient", "answer": REFUSAL, "sources": [], "confidence": "Low", "checks": [], "calculations": []}
            if not str(result.get("answer_markdown") or "").strip():
                claim_texts = [str(c.get("text") or "").strip() for c in result.get("claims") or []]
                result["answer_markdown"] = "\n\n".join(text for text in claim_texts if text)
            problems = verify(result, ev_by_id)
            answer = result.get("answer_markdown", "")
            calcs = []
            if not problems:
                for i, c in enumerate(result.get("calculations") or []):
                    val = calculate(c["expression"])
                    calcs.append({"label": c.get("label", ""), "expression": c["expression"], "result": round(val, 4)})
                    answer = answer.replace("{{calc:%d}}" % i, _fmt(val))
                if re.search(r"\{\{calc:\d+\}\}", answer):
                    problems.append("The answer referenced a calculation that was not defined.")
        if not problems:
            conf = str(result.get("confidence", "medium")).capitalize()
            if retried and conf == "High":
                conf = "Medium"
            checks = [f"{len(result['claims'])} claim(s) matched to quoted text on the cited pages"]
            if calcs:
                checks.append("Calculation computed and checked in Python")
            return {"status": "answered", "answer": answer, "sources": build_sources(result["claims"], ev_by_id),
                    "confidence": conf, "checks": checks, "calculations": calcs}
        logger.warning("Ollama answer failed verification: %s", problems)
        retried = True
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Verification failed:\n- " + "\n- ".join(problems) +
                      "\nFix these problems using only the evidence, or set can_answer to false. Reply with JSON only."}]

    return {"status": "insufficient", "answer": UNRELIABLE, "sources": [], "confidence": "Low", "checks": [], "calculations": []}
