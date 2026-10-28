"""End-to-end: the CLI writes the HTML brief. OCR and LLM are faked."""

import json

import pytest

from audit_prep import cli
from audit_prep.documents import OcrLine
from audit_prep.models import Item, Label
from audit_prep.rank import Brief, Section
from audit_prep.render import render_html
from fakes import FakeOcr

CERT_LINES = [
    OcrLine(text="Certificatenumber:QMS-48213", confidence=0.99, box=(82, 192, 380, 30)),
    OcrLine(text="Valid until: 01 December 2027", confidence=0.62, box=(79, 429, 360, 30)),
]


def _claim(thing, id, field, value, doc, page, quote):
    return {
        "thing": thing,
        "id": id,
        "field": field,
        "value": value,
        "doc_id": doc,
        "page": page,
        "quote": quote,
    }


# What the LLM "reads" from each page, when that page is among the passages it was given.
ON_PAGE = {
    ("DOC-CA12-EVID", 2): _claim(
        "CA", "CA-12", "status", "closed", "DOC-CA12-EVID", 2, "CA-12 was closed on 14 March 2026"
    ),
    ("DOC-MR-2026", 2): _claim(
        "supplier_evaluation",
        "2026",
        "status",
        "postponed",
        "DOC-MR-2026",
        2,
        "The annual supplier evaluation has been postponed to Q3 2026",
    ),
    ("SCAN-CERT-2024", 1): _claim(
        "certificate",
        "QMS-48213",
        "expiry_date",
        "2027-12-01",
        "SCAN-CERT-2024",
        1,
        "Valid until: 01 December 2027",
    ),
}


class PageLLM:
    """Answers with the claims for whichever known pages are in the prompt."""

    model_id = "fake/page-llm"

    def complete_json(self, system, user, schema):
        claims = [c for (doc, page), c in ON_PAGE.items() if f'doc="{doc}" page="{page}"' in user]
        return json.dumps({"claims": claims})


@pytest.fixture
def html(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "LlamaCppClient", lambda model: PageLLM())
    monkeypatch.setattr(cli, "RapidOcr", lambda: FakeOcr(CERT_LINES))
    out = tmp_path / "brief.html"

    assert cli.main(["--client", "rich-history", "--out", str(out)]) == 0
    return out.read_text(encoding="utf-8")


def test_cli_writes_brief_with_all_sections(html):
    for title in (
        "Needs attention",
        "Worth a look",
        "Not sampled in last 2 audits",
        "What I could not check",
    ):
        assert f"<h2>{title}</h2>" in html
    assert "Brightline Components Ltd" in html


def test_brief_shows_each_kind_of_item(html):
    assert "CA-12 open, 231 days overdue (clause 8.4)" in html  # 1 Fact
    assert "CA-12 status: record says open; DOC-CA12-EVID p.2 says closed" in html  # 3 Conflict
    assert "QMS-48213 status: record says open" not in html
    assert "certificate registry says suspended" in html  # 4 Conflict
    assert "supplier evaluation 2026 status: postponed" in html  # 5 Extracted
    assert "QMS-48213 expiry date: unreadable on SCAN-CERT-2024 p.1" in html  # 8 Missing
    assert "Internal audit report not submitted" in html  # 9 Missing    assert "AI-read" in html


def test_scan_item_has_crop(html):
    assert 'class="crop"' in html
    assert "background-position:-71px -421px" in html  # box (79, 429) minus the margin


def test_other_tenant_never_in_brief(html):  # 13
    assert "Harbor" not in html
    assert "DOC-HF" not in html


def test_document_text_is_escaped(tmp_path):
    hostile = Item(
        label=Label.MISSING, text="<script>alert(1)</script>", why="<b>x</b>", rule="test"
    )
    brief = Brief(
        tenant_id="cb-a",
        client_id="c",
        client_name="C",
        scheme="ISO 9001",
        audit={"id": "A", "type": "surveillance", "date": "2026-11-17"},
        sections=(Section(title="What I could not check", items=(hostile,)),),
    )
    page = render_html(brief, tmp_path)

    assert "<script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
