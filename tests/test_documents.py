"""Document tests: pages load per client, low-confidence OCR is flagged, search stays in tenant.

OCR is faked; the real engine is never run in tests.
"""

from pathlib import Path

import pytest

from audit_prep.documents import (
    KeywordIndex,
    OcrLine,
    Page,
    expand_terms,
    load_pages,
    low_confidence_lines,
)
from audit_prep.loader import load_audit
from audit_prep.models import Label, SourceKind


class FakeOcr:
    """Returns fixed lines, like RapidOCR would for the certificate scan."""

    def __init__(self, lines: list[OcrLine]) -> None:
        self.lines = lines

    def read(self, image: Path) -> list[OcrLine]:
        return self.lines


CERT_LINES = [
    OcrLine(text="Certificatenumber:QMS-48213", confidence=0.99, box=(82, 192, 380, 30)),
    OcrLine(text="Valid until: 01 December 2027", confidence=0.62, box=(79, 429, 360, 30)),
]


def _pages(tenant="cb-a", client="rich-history", lines=CERT_LINES):
    return load_pages(load_audit(tenant, client), FakeOcr(lines))


def test_loads_text_pages_and_scan():
    pages, items = _pages()

    assert items == ()
    by_doc = {(p.doc_id, p.page): p for p in pages}
    assert ("DOC-MR-2026", 3) in by_doc
    assert by_doc[("DOC-MR-2026", 2)].kind is SourceKind.DOCUMENT
    scan = by_doc[("SCAN-CERT-2024", 1)]
    assert scan.kind is SourceKind.SCAN
    assert "QMS-48213" in scan.text


def test_low_confidence_on_cited_line_is_flagged():
    pages, _ = _pages()
    scan = next(p for p in pages if p.kind is SourceKind.SCAN)

    [weak] = low_confidence_lines(scan, "01 December 2027")
    assert weak.box == (79, 429, 360, 30)  # kept for the scan crop in the brief
    assert low_confidence_lines(scan, "Certificate number: QMS-48213") == []  # spaces ignored


def test_text_pages_are_never_low_confidence():
    pages, _ = _pages()
    text_page = next(p for p in pages if p.kind is SourceKind.DOCUMENT)
    assert low_confidence_lines(text_page, "CA-12") == []


def test_unreadable_scan_is_missing():
    pages, items = _pages(lines=[])

    assert not any(p.doc_id == "SCAN-CERT-2024" for p in pages)
    [item] = items
    assert item.label is Label.MISSING
    assert "SCAN-CERT-2024" in item.text


def test_listed_document_without_file_is_missing(tmp_path):
    data = load_audit("cb-a", "thin-history")  # its document folder is not in tmp_path
    _, items = load_pages(data, FakeOcr([]), data_dir=tmp_path)

    [item] = items
    assert "DOC-KL-MR-2026" in item.text


def test_search_finds_ca12_pages_in_own_tenant_only():
    pages, _ = _pages()
    hits = KeywordIndex("cb-a", pages).search(["CA-12", "closed"])

    assert hits[0].page.doc_id == "DOC-CA12-EVID"  # "closed on 14 March"
    assert all(not h.page.doc_id.startswith("DOC-HF") for h in hits)  # CB-B's CA-12 never shows


def test_index_refuses_pages_from_another_tenant():
    cb_a, _ = _pages()
    cb_b, _ = _pages("cb-b", "harbor-foods")

    with pytest.raises(ValueError):
        KeywordIndex("cb-a", cb_a + cb_b)


def test_synonyms_from_profile_widen_the_search():
    profile = load_audit("cb-a", "rich-history").profile
    terms = expand_terms(["supplier evaluation"], profile)
    assert "vendor evaluation" in terms

    page = Page(
        tenant_id="cb-a",
        doc_id="D",
        page=1,
        kind=SourceKind.DOCUMENT,
        text="Vendor evaluation done.",
    )
    assert KeywordIndex("cb-a", (page,)).search(terms)
