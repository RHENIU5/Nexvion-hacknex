"""Question classification. Phase 1 uses heuristics; later phases route retrieval by modality."""
import re

MATH = re.compile(r"\b(calculate|percent|percentage|difference|change|increase|decrease|growth|average|total|sum|ratio|compare)\b", re.I)
CHART = re.compile(r"\b(chart|graph|figure|plot|trend|visualization|visualisation)\b", re.I)
TABLE = re.compile(r"\b(table|row|column|tabular)\b", re.I)
IMAGE = re.compile(r"\b(image|photo|picture|diagram|illustration|shown)\b", re.I)


def classify(question: str, n_docs: int) -> dict:
    modalities = ["text"]
    if TABLE.search(question): modalities.append("table")
    if CHART.search(question): modalities.append("chart")
    if IMAGE.search(question): modalities.append("image")
    return {"modalities": modalities, "needs_math": bool(MATH.search(question)), "multi_document": n_docs > 1}
