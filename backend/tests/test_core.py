import json
import re
import sys, pathlib, shutil
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import fitz, pytest
from calculator import calculate
from verifier import verify
from retriever import (
    is_visual_summary_request,
    requested_pages,
    retrieve,
    retrieve_visual_summary,
)
from retriever import is_summary_request
from document_processor import DocumentStore, STEPS
from citations import build_sources
from pdf_parser import _normalize_stacked_fractions, _select_vision_pages, parse_pdf
from question_router import classify
from reasoning import _client, _combine_document_summaries, _parse, answer_question
from vision_processor import VisionError, analyze_page


def test_calculator():
    assert round(calculate("(91.2 - 78.4) / 78.4 * 100"), 2) == 16.33
    with pytest.raises(ValueError):
        calculate("__import__('os').system('ls')")


def test_verifier_rejects_fake_quote():
    ev = {"a": {"content": "Efficiency in Q2 was 78.4%.", "id": "a"}}
    good = {
        "answer_markdown": "Efficiency in Q2 was 78.4%.",
        "claims": [{
            "text": "Efficiency in Q2 was 78.4%.",
            "evidence_ids": ["a"],
            "quote": "Efficiency in Q2 was 78.4%",
        }],
    }
    bad = {"claims": [{
        "text": "Efficiency in Q2 was 99%.",
        "evidence_ids": ["a"],
        "quote": "Efficiency in Q2 was 99%",
    }]}
    assert verify(good, ev) == [] and verify(bad, ev)
    calc = {**good, "calculations": [{"expression": "78.4 + 5", "evidence_ids": ["a"]}]}
    assert verify(calc, ev)  # 5 not in evidence


def test_ocr_quote_matching_tolerates_one_word_difference_and_cites_source_text():
    evidence = {
        "ocr": {
            "content": "Can have set of values for\nparticular entity.",
            "id": "ocr", "doc_id": "a", "document": "notes.pdf", "page": 4,
            "type": "ocr",
        },
    }
    result = {
        "answer_markdown": "Multivalued attributes can have a set of values for an entity.",
        "claims": [{
            "text": "Multivalued attributes can have a set of values for an entity.",
            "evidence_ids": ["ocr"],
            "quote": "Have a set of values for a particular entity.",
        }],
    }

    assert verify(result, evidence) == []
    source = build_sources(result["claims"], evidence)[0]
    assert source["snippet"] == "have set of values for\nparticular entity"


def test_ocr_quote_matching_still_rejects_substantially_different_text():
    evidence = {
        "ocr": {"content": "Can have set of values for a particular entity.", "type": "ocr"},
        "text": {"content": "Can have set of values for a particular entity.", "type": "text"},
    }

    assert verify({
        "claims": [{
            "text": "Values can be anything at all.",
            "evidence_ids": ["ocr"],
            "quote": "Values are always stored in a database with no limitations.",
        }],
    }, evidence)
    assert verify({
        "claims": [{
            "text": "Multivalued attributes have a set of values.",
            "evidence_ids": ["text"],
            "quote": "Have a set of values for a particular entity.",
        }],
    }, evidence)


def test_quote_matching_ignores_extraction_inserted_spaces_without_changing_words():
    evidence = {
        "text": {
            "content": "The model *relied* on a given input, not that the feature causes a site.",
            "type": "text",
        },
    }
    claim = {
        "text": "The model relied on an input, not that the feature caused a site.",
        "evidence_ids": ["text"],
        "quote": "The model relied on a given input, not that the feature causes a site.",
    }

    result = {"answer_markdown": claim["text"], "claims": [claim]}
    assert verify(result, evidence) == []
    claim["quote"] = "The model relied on a given input proving the feature causes a site."
    assert verify(result, evidence)


def test_quote_matching_allows_exact_ordered_ellipsis_spans():
    evidence = {
        "ocr": {
            "content": "Enhanced ER Model. Generalization: Bottom-up approach. Specialization: Top-down approach.",
            "type": "ocr",
        },
    }

    assert verify({
        "answer_markdown": "The page introduces generalization and specialization.",
        "claims": [{
            "text": "The page introduces generalization and specialization.",
            "evidence_ids": ["ocr"],
            "quote": "Enhanced ER Model ... Specialization: Top-down approach.",
        }],
    }, evidence) == []
    assert verify({
        "answer_markdown": "Unsupported quote.",
        "claims": [{
            "text": "Unsupported quote.",
            "evidence_ids": ["ocr"],
            "quote": "Enhanced ER Model ... Specialization proves any entity is valid.",
        }],
    }, evidence)


def test_citations_only_show_sources_containing_the_claim_quote():
    evidence = {
        "summary": {
            "id": "summary", "doc_id": "a", "document": "report.pdf", "page": 1,
            "type": "text", "content": "Production efficiency improved during 2026.",
        },
        "unrelated": {
            "id": "unrelated", "doc_id": "a", "document": "report.pdf", "page": 3,
            "type": "text", "content": "Plant A improved from 80.2% to 93.1%.",
        },
    }
    claims = [{
        "evidence_ids": ["summary", "unrelated"],
        "quote": "Production efficiency improved during 2026.",
    }]

    sources = build_sources(claims, evidence)

    assert [source["evidence_id"] for source in sources] == ["summary"]


def test_multi_document_summaries_keep_each_answer_and_source():
    results = [
        {
            "answer": "Production improved.",
            "sources": [{"evidence_id": "report-p2", "document": "report.pdf"}],
            "confidence": "High", "checks": ["1 claim verified"], "calculations": [],
        },
        {
            "answer": "The notes explain classification metrics.",
            "sources": [{"evidence_id": "notes-p1", "document": "notes.pdf"}],
            "confidence": "Medium", "checks": ["2 claims verified"], "calculations": [],
        },
    ]

    combined = _combine_document_summaries(results)

    assert combined["status"] == "answered"
    assert "**report.pdf**" in combined["answer"] and "**notes.pdf**" in combined["answer"]
    assert {source["evidence_id"] for source in combined["sources"]} == {"report-p2", "notes-p1"}
    assert combined["confidence"] == "Medium"


def test_multi_document_summary_falls_back_to_cited_excerpts(monkeypatch):
    class Response:
        content = [type("Block", (), {
            "text": json.dumps({"can_answer": False}),
        })()]

    class Messages:
        def create(self, **kwargs):
            return Response()

    class Client:
        messages = Messages()

    monkeypatch.setattr("reasoning._client", lambda: Client())
    evidence = [
        {
            "id": "report-p2", "doc_id": "report", "document": "report.pdf",
            "page": 2, "type": "text",
            "content": "Production efficiency increased from 78% in Q2 to 91% in Q4.",
        },
        {
            "id": "notes-p3", "doc_id": "notes", "document": "notes.pdf",
            "page": 3, "type": "table",
            "content": "Cause | Share of losses | Material delays | 31%.",
        },
    ]

    result = answer_question(
        "Summarize all selected documents",
        evidence,
        {"multi_document": True, "modalities": ["text"], "needs_math": False},
    )

    assert result["status"] == "answered"
    assert "**report.pdf**" in result["answer"]
    assert "**notes.pdf**" in result["answer"]
    assert "direct extracts" in result["answer"]
    assert {(source["document"], source["page"]) for source in result["sources"]} == {
        ("report.pdf", 2), ("notes.pdf", 3),
    }
    assert all("exact extracted passages" in check for check in result["checks"])


def test_visual_summary_retrieval_finds_figures_and_skips_test_metadata():
    evidence = [
        {"id": "intro", "doc_id": "a", "page": 1, "type": "text",
         "content": "A synthetic test corpus designed to test charts and visual reasoning."},
        {"id": "chart", "doc_id": "a", "page": 4, "type": "text",
         "content": "Figure 1 — chart shows production efficiency improving from Q1 to Q4."},
        {"id": "inspection", "doc_id": "a", "page": 6, "type": "text",
         "content": "Visual evidence: inspection station B recorded the highest defect concentration."},
        {"id": "body", "doc_id": "a", "page": 8, "type": "text",
         "content": "The operations team improved maintenance staffing during the quarter."},
        {"id": "diagram", "doc_id": "a", "page": 9, "type": "diagram",
         "content": "Production workflow diagram: Assembly, Inspection, Packing."},
        {"id": "index", "doc_id": "a", "page": 11, "type": "text",
         "content": "Evidence map: Figure 1 is a chart and Figure 2 is an image."},
    ]

    hits = retrieve_visual_summary(evidence)

    assert {item["id"] for item in hits} == {"chart", "inspection", "diagram"}
    assert next(item for item in hits if item["id"] == "chart")["type"] == "chart"
    assert next(item for item in hits if item["id"] == "inspection")["type"] == "image"
    assert is_visual_summary_request(
        "what are image content in this and need a summary about the images in the pdf"
    )


def test_multi_document_visual_summary_reports_extracted_visuals_and_missing_evidence():
    evidence = [
        {
            "id": "chart-a", "doc_id": "a", "document": "visuals.pdf", "page": 4,
            "type": "text", "content": "Figure 1 — chart shows production efficiency improving from Q1 to Q4.",
        },
        {
            "id": "image-a", "doc_id": "a", "document": "visuals.pdf", "page": 6,
            "type": "image", "content": "Inspection image shows the highest defect concentration at station B.",
        },
        {
            "id": "body-b", "doc_id": "b", "document": "notes.pdf", "page": 1,
            "type": "text", "content": "The operations team improved maintenance staffing.",
        },
    ]

    result = answer_question(
        "Summarize the images in these PDFs.",
        evidence,
        {"multi_document": True, "modalities": ["text"], "needs_math": False},
    )

    assert result["status"] == "answered"
    assert "**visuals.pdf**" in result["answer"]
    assert "**notes.pdf**" in result["answer"]
    assert "Chart · page 4" in result["answer"]
    assert "Image · page 6" in result["answer"]
    assert "No image, chart, figure, or diagram evidence was extracted" in result["answer"]
    assert [(source["document"], source["page"], source["type"]) for source in result["sources"]] == [
        ("visuals.pdf", 4, "chart"),
        ("visuals.pdf", 6, "image"),
    ]


def test_requested_pages_parses_lists_and_ranges():
    assert requested_pages("summarize pg 40,41,42 into txt and give here") == [40, 41, 42]
    assert requested_pages("summarize pages 40–42 into text") == [40, 41, 42]
    assert requested_pages("give me a summary for pages 40 to 42") == [40, 41, 42]
    assert requested_pages("summarize pages 40 and 42") == [40, 42]
    assert requested_pages("summarize page 40") == [40]
    assert requested_pages("summarize this document") == []


def test_page_summary_uses_only_requested_page_evidence(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.content = [type("Block", (), {"text": json.dumps(payload)})()]

    class Messages:
        def __init__(self):
            self.pages = []

        def create(self, **kwargs):
            prompt = kwargs["messages"][0]["content"]
            page = int(re.search(r"\[p(40|41|42)\]", prompt).group(1))
            self.pages.append(page)
            quote = {
                40: "Attributes of Relationship Types",
                41: "some attributes can be determined",
                42: "Enhanced ER Model",
            }[page]
            return Response({
                "can_answer": True,
                "answer_markdown": "This unsupported answer-markdown must not be shown.",
                "claims": [{
                    "text": f"Page {page} explains {quote}.",
                    "evidence_ids": [f"p{page}"],
                    "quote": quote,
                }],
                "calculations": [],
                "confidence": "high",
            })

    class Client:
        def __init__(self):
            self.messages = Messages()

    client = Client()
    monkeypatch.setattr("reasoning._client", lambda: client)
    evidence = [
        {
            "id": f"p{page}", "doc_id": "a", "document": "diagrams.pdf", "page": page,
            "type": "ocr", "content": content,
        }
        for page, content in (
            (40, "OCR text: Attributes of Relationship Types can be migrated."),
            (41, "OCR text: In M:N relationship type, some attributes can be determined by a combination."),
            (42, "OCR text: Enhanced ER Model. Generalization and Specialization."),
            (43, "This page must not appear in a summary of pages 40–42."),
        )
    ]

    result = answer_question(
        "summarize pg 40,41,42 into txt and give here",
        evidence,
        {"multi_document": False, "modalities": ["text"], "needs_math": False},
    )

    assert result["status"] == "answered"
    assert {source["page"] for source in result["sources"]} == {40, 41, 42}
    assert all(source["page"] != 43 for source in result["sources"])
    assert "```" not in result["answer"]
    assert "unsupported answer-markdown" not in result["answer"]
    assert client.messages.pages == [40, 41, 42]


def test_page_summary_shows_ocr_text_when_model_summary_cannot_be_verified(monkeypatch):
    class Response:
        content = [type("Block", (), {
            "text": json.dumps({
                "can_answer": True,
                "answer_markdown": "Unsupported generated summary.",
                "claims": [],
                "calculations": [],
                "confidence": "high",
            }),
        })()]

    class Messages:
        def create(self, **kwargs):
            return Response()

    class Client:
        messages = Messages()

    monkeypatch.setattr("reasoning._client", lambda: Client())
    evidence = [{
        "id": "page40", "doc_id": "a", "document": "diagram.pdf", "page": 40,
        "type": "ocr",
        "content": "OCR text:\n* Relationships\n* Attributes of Relationship Types\n"
                   "In 1:1 relationship type, attributes can be migrated to either entity type.",
    }]

    result = answer_question(
        "summarize page 40 into text",
        evidence,
        {"multi_document": False, "modalities": ["text"], "needs_math": False},
    )

    assert result["status"] == "answered"
    assert "Extracted text (OCR; summary could not be verified)" in result["answer"]
    assert "Attributes of Relationship Types" in result["answer"]
    assert "Unsupported generated summary" not in result["answer"]
    assert result["sources"][0]["page"] == 40
    assert "showing extracted OCR/text instead" in result["checks"][0]


def test_document_store_inspects_requested_pages_on_demand(tmp_path, monkeypatch):
    pdf = fitz.open()
    pdf.new_page()
    path = tmp_path / "visual.pdf"
    pdf.save(path)
    store = DocumentStore(tmp_path / "store")
    meta = store.create("visual.pdf", path.read_bytes())
    store._meta[meta["id"]].update(status="ready", pages=1)
    store._save_meta(meta["id"])
    calls = []

    def fake_analyze_page(page, page_number):
        calls.append(page_number)
        return [{
            "type": "diagram",
            "content": "Workflow diagram: Assembly then Inspection.",
            "bounding_box": [0.1, 0.1, 0.9, 0.9],
            "confidence": 0.7,
        }]

    monkeypatch.setattr("document_processor.analyze_page", fake_analyze_page)

    evidence, warnings = store.inspect_pages([meta["id"]], [1, 2])

    assert calls == [1]
    assert warnings == []
    assert evidence[0]["page"] == 1
    assert evidence[0]["type"] == "diagram"
    assert evidence[0]["doc_id"] == meta["id"]


def test_parse_and_retrieve(tmp_path):
    pdf = fitz.open(); p = pdf.new_page()
    p.insert_text((72, 72), "4.2 Downtime", fontsize=18)
    p.insert_text((72, 120), "Machine downtime decreased from 12.5% in Q2 to 6.8% in Q4.", fontsize=11)
    pdf.new_page()  # blank "scanned" page
    pdf.save(tmp_path / "t.pdf")
    r = parse_pdf(tmp_path / "t.pdf", "abcdef123456", "t.pdf")
    assert r.pages == 2 and r.evidence[0]["section"] == "4.2 Downtime" and r.evidence[0]["page"] == 1
    assert any("Page 2" in w for w in r.warnings)
    assert retrieve("downtime Q4", r.evidence)[0]["page"] == 1


def test_vision_page_selection_is_bounded_and_prioritizes_vector_diagrams():
    pages = [
        {"has_visual": True, "images": [object()], "vector_visual": False}
        for _ in range(57)
    ]
    pages[43] = {"has_visual": True, "images": [], "vector_visual": True}
    pages[44] = {"has_visual": True, "images": [], "vector_visual": True}

    selected = _select_vision_pages(pages)

    assert len(selected) == 4
    assert {43, 44} <= selected
    assert min(selected) >= 0 and max(selected) < len(pages)


def test_quick_actions_retrieve_broad_evidence():
    evidence = [
        {"id": "a1", "doc_id": "a", "page": 1, "type": "text", "content": "The program improved operations."},
        {"id": "a2", "doc_id": "a", "page": 2, "type": "ocr", "content": "Output increased by 25 percent."},
        {"id": "b1", "doc_id": "b", "page": 1, "type": "text", "content": "The project reduced costs."},
        {"id": "b2", "doc_id": "b", "page": 2, "type": "table", "content": "Annual savings were 1200 dollars."},
    ]

    summary = retrieve("Summarize this document", evidence)
    comparison = retrieve("Compare the main findings", evidence)
    numbers = retrieve("Extract key numbers", evidence)
    supporting = retrieve("Find supporting evidence", evidence)

    assert summary and {"text", "ocr", "table"} <= {item["type"] for item in summary}
    assert supporting
    assert {item["doc_id"] for item in comparison} == {"a", "b"}
    assert numbers[0]["id"] in {"a2", "b2"}
    assert is_summary_request("Summarize this document")
    assert is_summary_request("I'm asking for all 3 docs which are uploaded")
    assert not is_summary_request("Compare the main findings")


def test_summary_retrieval_covers_pages_and_multimodal_evidence():
    evidence = [
        {"id": f"text-{page}", "doc_id": "a", "page": page, "type": "text",
         "content": f"Page {page} describes important project results and findings."}
        for page in range(1, 12)
    ]
    evidence += [
        {"id": "table", "doc_id": "a", "page": 7, "type": "table",
         "content": "Cause | Share of losses | Materials 31% | Calibration 24%"},
        {"id": "chart", "doc_id": "a", "page": 5, "type": "chart",
         "content": "Efficiency and quality improve each quarter."},
        {"id": "image", "doc_id": "a", "page": 6, "type": "image",
         "content": "A production workflow diagram."},
    ]

    hits = retrieve("Summarize this document", evidence)

    assert len({item["page"] for item in hits if item["type"] == "text"}) == 8
    assert {"table", "chart", "image"} <= {item["type"] for item in hits}
    assert "text-11" in {item["id"] for item in hits}


def test_summary_retrieval_skips_cover_and_test_question_pages():
    evidence = [
        {"id": "cover", "doc_id": "a", "page": 1, "type": "text",
         "section": "Test Corpus", "content": "A synthetic document designed to test AI capabilities."},
        {"id": "summary", "doc_id": "a", "page": 2, "type": "text",
         "section": "Executive Summary", "content": "Efficiency increased from 78% to 91%."},
        {"id": "causes", "doc_id": "a", "page": 7, "type": "text",
         "section": "Root Cause Analysis", "content": "Material delays caused 31% of losses."},
        {"id": "questions", "doc_id": "a", "page": 11, "type": "text",
         "section": "Recommended Test Questions", "content": "What caused the efficiency change?"},
        {"id": "question-table", "doc_id": "a", "page": 11, "type": "table",
         "section": "Recommended Test Questions", "content": "Question | What caused the change?"},
    ]

    hits = retrieve("Summarize this document", evidence, top_k=4)

    assert "cover" not in {item["id"] for item in hits}
    assert "questions" not in {item["id"] for item in hits}
    assert "question-table" not in {item["id"] for item in hits}
    assert {"summary", "causes"} <= {item["id"] for item in hits}


def test_retrieval_balances_matching_multimodal_evidence():
    evidence = [
        {"id": "text", "doc_id": "a", "type": "text", "content": "Production efficiency improved from Q2 to Q4."},
        {"id": "table", "doc_id": "a", "type": "table", "content": "Metric | Production efficiency | Q2 | 78% | Q4 | 91%"},
        {"id": "chart", "doc_id": "a", "type": "chart", "content": "Efficiency chart shows Q2 at 78% and Q4 at 91%."},
        {"id": "image", "doc_id": "a", "type": "image", "content": "Inspection image shows defects at Q4."},
    ]
    hits = retrieve("Compare production efficiency Q2 and Q4 using table and chart evidence", evidence)

    assert {"text", "table", "chart"} <= {item["type"] for item in hits}
    assert classify("Compare production efficiency in the chart and table", 1)["modalities"] == ["text", "table", "chart"]


def test_retrieval_finds_cause_table_for_reason_questions():
    evidence = [
        {"id": "metrics", "doc_id": "a", "type": "table",
         "content": "Metric | Production Efficiency | Q2 78.4% | Q4 91.2% | Change +12.8 pp"},
        {"id": "chart", "doc_id": "a", "type": "chart",
         "content": "Efficiency rises from Q2 to Q4."},
        {"id": "causes", "doc_id": "a", "type": "table",
         "content": "Cause | Share of Loss Events | Material shortages 31% | Calibration delays 24%"},
    ]

    hits = retrieve(
        "Compare production efficiency between Q2 and Q4, identify the three biggest reasons for the change, and show me the proof.",
        evidence,
    )

    assert "causes" in {item["id"] for item in hits}
    assert "metrics" in {item["id"] for item in hits}


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract OCR is not installed")
def test_parse_pdf_reads_formula_from_embedded_image(tmp_path, monkeypatch):
    monkeypatch.setattr("pdf_parser.analyze_page", lambda page, page_number, has_native_table=False: [])
    source = fitz.open()
    page = source.new_page()
    page.insert_text((60, 120), "Precision = TP / (TP + FP)", fontsize=32)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(3, 3))

    scanned = fitz.open()
    image_page = scanned.new_page()
    image_page.insert_image(image_page.rect, pixmap=pixmap)
    pdf_path = tmp_path / "formula.pdf"
    scanned.save(pdf_path)

    result = parse_pdf(pdf_path, "formula123456", "formula.pdf")
    ocr_evidence = [item for item in result.evidence if item["type"] == "ocr"]

    assert ocr_evidence
    assert any("Precision" in item["content"] and "TP" in item["content"] for item in ocr_evidence)
    assert retrieve("precision formula", result.evidence)


def test_ocr_reconstructs_stacked_formula_layout():
    formulas = _normalize_stacked_fractions("_. TP\nPrecision = ———\nTP+FP")

    assert formulas == ["Formula layout reconstructed from OCR: Precision = TP / (TP+FP)"]


def test_multimodal_pipeline_extracts_table_and_indexes_visuals(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pdf_parser.analyze_page",
        lambda page, page_number, has_native_table=False: [{
            "type": "chart",
            "label": "Output by quarter",
            "content": "Output by quarter: Output rises from Q2 to Q4.",
            "bounding_box": [0.5, 0.2, 0.9, 0.6],
            "confidence": 0.7,
        }],
    )
    pdf = fitz.open()
    page = pdf.new_page(width=600, height=800)
    for y in (50, 95, 140):
        page.draw_line((50, y), (230, y), width=1)
    for x in (50, 140, 230):
        page.draw_line((x, 50), (x, 140), width=1)
    page.insert_text((60, 78), "Period", fontsize=10)
    page.insert_text((150, 78), "Output", fontsize=10)
    page.insert_text((60, 120), "Q2", fontsize=10)
    page.insert_text((150, 120), "100", fontsize=10)
    page.insert_text((50, 180), "Quarterly production output", fontsize=14)
    page.draw_line((320, 250), (320, 400), width=2)
    page.draw_line((320, 400), (520, 400), width=2)
    points = [(340, 370), (390, 350), (440, 310), (500, 270)]
    for start, end in zip(points, points[1:]):
        page.draw_line(start, end, width=2)
    for y in (300, 350):
        page.draw_line((320, y), (520, y), width=0.5)
    pdf_path = tmp_path / "multimodal.pdf"
    pdf.save(pdf_path)

    stages = []
    result = parse_pdf(
        pdf_path, "multimodal123", "multimodal.pdf",
        lambda stage, done, total: stages.append(stage),
    )
    table_evidence = [item for item in result.evidence if item["type"] == "table"]
    chart_evidence = [item for item in result.evidence if item["type"] == "chart"]

    assert table_evidence and "Q2 | 100" in table_evidence[0]["content"]
    assert chart_evidence and chart_evidence[0]["bounding_box"] == [0.5, 0.2, 0.9, 0.6]
    assert retrieve("output quarter Q2", result.evidence)
    assert stages == ["page_detection", "text_extraction", "visual_analysis"]

    store = DocumentStore(tmp_path / "store")
    meta = store.create("multimodal.pdf", pdf_path.read_bytes())
    store.process(meta["id"])
    completed = store.get(meta["id"])
    assert completed["status"] == "ready" and completed["progress"] == 100
    assert [step["label"] for step in completed["steps"]] == STEPS
    assert all(step["done"] for step in completed["steps"])


def test_stale_documents_retry_vision_when_model_becomes_available(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_VISION_MODEL", "llava:latest")
    monkeypatch.setattr("document_processor.model_available", lambda: True)
    pdf = fitz.open()
    pdf.new_page()
    path = tmp_path / "stale.pdf"
    pdf.save(path)
    store = DocumentStore(tmp_path / "store")
    meta = store.create("stale.pdf", path.read_bytes())
    stored = store.get(meta["id"])
    stored.update(
        status="ready", parser_version=6, vision_incomplete=True,
        vision_model="llava:latest",
        warnings=["Visual analysis could not run on pages 1. Details: HTTP Error 404: Not Found"],
    )
    store._save_meta(meta["id"])

    assert store.schedule_stale_documents() == [meta["id"]]
    assert store.get(meta["id"])["status"] == "processing"


def test_abandoned_processing_documents_are_queued_once(tmp_path):
    store = DocumentStore(tmp_path / "store")
    meta = store.create("interrupted.pdf", b"%PDF")

    assert store.schedule_stale_documents() == [meta["id"]]
    assert store.schedule_stale_documents() == []


def test_vision_processor_structures_image_only_table(monkeypatch):
    response_body = {
        "message": {
            "content": '{"visuals":[{"type":"table","label":"Quarterly output",'
                       '"description":"Output by quarter","rows":[["Quarter","Units"],["Q2","42800"]],'
                       '"bbox":[0.1,0.2,0.8,0.6]}]}'
        }
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(response_body).encode()

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr("vision_processor.urllib.request.urlopen", fake_urlopen)
    doc = fitz.open()
    page = doc.new_page()
    evidence = analyze_page(page, 1)

    assert evidence[0]["type"] == "table"
    assert "Q2 | 42800" in evidence[0]["content"]
    assert evidence[0]["bounding_box"] == [0.1, 0.2, 0.8, 0.6]
    prompt = requests[0]["messages"][0]["content"]
    assert "at most 4 rows and 6 cells per row" in prompt
    assert requests[0]["options"]["num_predict"] == 500


def test_vision_processor_reports_invalid_model_json_without_retry(monkeypatch):
    responses = iter([{"message": {"content": '{"visuals": ['}}])
    requests = []

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(next(responses)).encode()

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data))
        return Response(None)

    monkeypatch.setattr("vision_processor.urllib.request.urlopen", fake_urlopen)
    doc = fitz.open()
    page = doc.new_page()

    with pytest.raises(VisionError, match="invalid JSON"):
        analyze_page(page, 1)
    assert len(requests) == 1


def test_ollama_client_uses_local_endpoint_without_anthropic_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = _client()
    assert str(client.base_url).rstrip("/") == "http://localhost:11434"
    assert client.api_key == "ollama"


def test_parser_repairs_newlines_inside_model_json_strings():
    parsed = _parse('{"answer_markdown":"First line\nSecond line","claims":[]}')
    assert parsed["answer_markdown"] == "First line\nSecond line"


def test_parser_repairs_invalid_backslashes_in_ocr_quotes():
    parsed = _parse(r'{"quote":"Weak Entity Type: Bank Branch, \ [ = \ gam"}')

    assert parsed["quote"] == "Weak Entity Type: Bank Branch, \\ [ = \\ gam"
