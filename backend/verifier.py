"""Answer verification: every claim must cite real evidence and quote text that is actually on the cited page."""
import re

from calculator import calculate

ALLOWED_CONSTANTS = {"100", "1", "2"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip().lower()


def numbers_in(s: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*\.?\d*", s)}


def _clean(n: str) -> str:
    return n.rstrip(".")


def _token_edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_token in enumerate(left, 1):
        current = [left_index]
        for right_index, right_token in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_token != right_token),
            ))
        previous = current
    return previous[-1]


def find_quote_match(quote: str, content: str, allow_ocr: bool = False) -> str | None:
    fragments = [fragment.strip() for fragment in re.split(r"\.{3,}|…", quote) if fragment.strip()]
    if len(fragments) > 1:
        start, end = 0, 0
        for fragment in fragments:
            compact_fragment = "".join(char.lower() for char in fragment if char.isalnum())
            compact_content = "".join(char.lower() for char in content if char.isalnum())
            found = compact_content.find(compact_fragment, start)
            if not compact_fragment or found < 0:
                return None
            if start == 0:
                first = found
            start = found + len(compact_fragment)
            end = start
        positions = [index for index, char in enumerate(content) if char.isalnum()]
        return content[positions[first]:positions[end - 1] + 1]

    compact_quote = "".join(char.lower() for char in quote if char.isalnum())
    compact_content, positions = [], []
    for index, char in enumerate(content):
        if char.isalnum():
            compact_content.append(char.lower())
            positions.append(index)
    compact_content = "".join(compact_content)
    compact_start = compact_content.find(compact_quote) if compact_quote else -1
    if compact_start >= 0:
        compact_end = compact_start + len(compact_quote) - 1
        return content[positions[compact_start]:positions[compact_end] + 1]

    quote_tokens = list(re.finditer(r"\b[\w']+\b", quote, re.UNICODE))
    content_tokens = list(re.finditer(r"\b[\w']+\b", content, re.UNICODE))
    if not quote_tokens or not content_tokens:
        return None

    normalized_quote = [token.group().lower() for token in quote_tokens]
    normalized_content = [token.group().lower() for token in content_tokens]
    quote_length = len(normalized_quote)
    # Longer OCR quotes can differ by a couple of words when columns are merged.
    max_edits = 2 if allow_ocr and quote_length >= 8 else 0
    best_match = None
    best_distance = max_edits + 1
    window_sizes = range(max(1, quote_length - max_edits), quote_length + max_edits + 1)
    for window_size in window_sizes:
        for start in range(len(content_tokens) - window_size + 1):
            candidate_tokens = normalized_content[start:start + window_size]
            distance = _token_edit_distance(normalized_quote, candidate_tokens)
            if distance < best_distance:
                best_distance = distance
                best_match = content[
                    content_tokens[start].start():content_tokens[start + window_size - 1].end()
                ]
            if distance == 0:
                return best_match

    return best_match if best_distance <= max_edits else None


def verify(result: dict, ev_by_id: dict) -> list[str]:
    problems = []
    answer = result.get("answer_markdown")
    if not isinstance(answer, str) or not answer.strip():
        problems.append("The answer text is empty.")
    claims = result.get("claims") or []
    if not claims:
        problems.append("No claims with evidence were provided.")
    for i, c in enumerate(claims, 1):
        if not str(c.get("text") or "").strip():
            problems.append(f"Claim {i} has no answer text.")
        ids = c.get("evidence_ids") or []
        if not ids:
            problems.append(f"Claim {i} cites no evidence.")
        for eid in ids:
            if eid not in ev_by_id:
                problems.append(f"Claim {i} cites unknown evidence id '{eid}'.")
        quote = norm(c.get("quote") or "")
        known = [ev_by_id[e] for e in ids if e in ev_by_id]
        if not quote:
            problems.append(f"Claim {i} has no supporting quote.")
        elif known and not any(
            find_quote_match(
                c.get("quote") or "",
                e["content"],
                allow_ocr=e.get("type") == "ocr",
            )
            for e in known
        ):
            problems.append(f"Claim {i}: the quote was not found verbatim in the cited evidence.")
    for i, calc in enumerate(result.get("calculations") or []):
        ids = calc.get("evidence_ids") or []
        text = " ".join(ev_by_id[e]["content"] for e in ids if e in ev_by_id)
        have = {_clean(n) for n in numbers_in(text)}
        for n in numbers_in(calc.get("expression", "")):
            n = _clean(n)
            if n not in have and n not in ALLOWED_CONSTANTS:
                problems.append(f"Calculation {i}: the number {n} does not appear in the cited evidence.")
        try:
            calculate(calc.get("expression", ""))
        except Exception:
            problems.append(f"Calculation {i}: the expression could not be evaluated.")
    return problems
