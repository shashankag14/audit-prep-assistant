"""Check tests: one per label path, on the real synthetic pages. Numbers = planted issues."""

import pytest

from audit_prep.checks import quote_on_page, record_claims, run_checks
from audit_prep.documents import OcrLine, load_pages
from audit_prep.external import registry_claims
from audit_prep.loader import load_audit
from audit_prep.models import Claim, Label, Source, SourceKind
from audit_prep.quality import check_quality
from fakes import FakeOcr

CERT_LINES = [
    OcrLine(text="Certificatenumber:QMS-48213", confidence=0.99, box=(82, 192, 380, 30)),
    OcrLine(text="Valid until: 01 December 2027", confidence=0.62, box=(79, 429, 360, 30)),
]


@pytest.fixture(scope="module")
def rich():
    data = load_audit("cb-a", "rich-history")
    records = check_quality(data.records).records
    pages, _ = load_pages(data, FakeOcr(CERT_LINES))
    return data, records, pages


def _doc(id, field, value, quote, thing="CA", doc="DOC-CA12-EVID", page=2):
    source = Source(kind=SourceKind.DOCUMENT, ref=doc, page=page, quote=quote)
    return Claim(thing=thing, id=id, field=field, value=value, source=source)


def _check(rich, *claims, external=()):
    data, records, pages = rich
    others = record_claims(records, data.profile) + tuple(external)
    return run_checks(tuple(claims), pages, others)


def test_record_claims_use_profile_fields(rich):
    data, records, _ = rich
    claims = {(c.id, c.field): c.value for c in record_claims(records, data.profile)}

    assert claims[("CA-12", "status")] == "open"
    assert claims[("QMS-48213", "status")] == "valid"
    assert ("CA-12", "closed_on") not in claims  # null in the records: no claim


def test_document_vs_record_is_conflict(rich):  # 3
    closed = _doc("CA-12", "status", "closed", "CA-12 was closed on 14 March 2026")
    [item] = _check(rich, closed)

    assert item.label is Label.CONFLICT
    assert item.text == "CA-12 status: record says open; DOC-CA12-EVID p.2 says closed"
    assert {s.kind for s in item.sources} == {SourceKind.RECORD, SourceKind.DOCUMENT}


def test_registry_vs_record_is_conflict(rich):  # 4
    _, records, _ = rich
    items = {i.text.split(":")[0]: i for i in _check(rich, external=registry_claims(records))}

    status = items["QMS-48213 status"]
    assert status.label is Label.CONFLICT
    assert "certificate registry says suspended" in status.text
    assert items["QMS-48213 expiry date"].label is Label.EXTRACTED  # agrees with the record


def test_postponed_evaluation_is_extracted(rich):  # 5
    postponed = _doc(
        "2026",
        "status",
        "postponed",
        "The annual supplier evaluation has been postponed to Q3 2026",
        thing="supplier_evaluation",
        doc="DOC-MR-2026",
    )
    [item] = _check(rich, postponed)

    assert item.label is Label.EXTRACTED
    assert item.text == "supplier evaluation 2026 status: postponed"


def test_invented_quote_is_missing(rich):  # 7
    invented = _doc("CA-12", "status", "closed", "CA-12 was verified effective by the auditor")
    [item] = _check(rich, invented)

    assert item.label is Label.MISSING
    assert item.sources == ()  # an invented quote is never shown as evidence


def test_small_slip_in_quote_is_still_found(rich):
    slip = _doc("CA-12", "status", "closed", "CA-12 was c1osed on 14 March  2026")
    [item] = _check(rich, slip)
    assert item.label is Label.CONFLICT


def test_unreadable_scan_line_is_missing(rich):  # 8
    quote = "Valid until: 01 December 2027"
    source = Source(
        kind=SourceKind.SCAN, ref="SCAN-CERT-2024", page=1, quote=quote, box=(79, 429, 360, 30)
    )
    expiry = Claim(
        thing="certificate", id="QMS-48213", field="expiry_date", value="2027-12-01", source=source
    )
    [item] = _check(rich, expiry)

    assert item.label is Label.MISSING
    assert item.sources[0].box == (79, 429, 360, 30)  # for the scan crop


def test_new_value_with_no_record_is_extracted(rich):
    closed_on = _doc("CA-12", "closed_on", "2026-03-14", "CA-12 was closed on 14 March 2026")
    [item] = _check(rich, closed_on)

    assert item.label is Label.EXTRACTED  # closed_on is null in the records: nothing to compare
    assert item.why == "quote found on the cited page"


def test_scan_quote_ignores_ocr_spacing(rich):
    _, _, pages = rich
    scan = next(p for p in pages if p.kind is SourceKind.SCAN)
    assert quote_on_page("Certificate number: QMS-48213", scan)
    assert not quote_on_page("Certificate number: QMS-99999", scan)


def test_registry_matches_by_certificate_number():
    thin = load_audit("cb-a", "thin-history").records
    assert {c.field: c.value for c in registry_claims(thin)}["status"] == "valid"
    assert registry_claims({"certificate": {"number": "QMS-00000"}}) == ()
    assert registry_claims({}) == ()
