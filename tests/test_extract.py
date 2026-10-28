"""Extraction tests. The LLM is faked: each test scripts the model's answers."""

import json

import pytest

from audit_prep.documents import KeywordIndex, OcrLine, load_pages
from audit_prep.extract import Question, build_questions, extract_claims
from audit_prep.loader import load_audit
from audit_prep.models import Label, SourceKind
from audit_prep.quality import check_quality
from audit_prep.rules import run_rules
from fakes import FakeLLM, FakeOcr

CERT_LINES = [
    OcrLine(text="Certificatenumber:QMS-48213", confidence=0.99, box=(82, 192, 380, 30)),
    OcrLine(text="Valid until: 01 December 2027", confidence=0.62, box=(79, 429, 360, 30)),
]

CA12 = Question(id="CA-12", text="What do the documents say about CA-12?", terms=("CA-12",))

CA12_CLOSED = {
    "thing": "CA",
    "id": "CA-12",
    "field": "status",
    "value": "closed",
    "doc_id": "DOC-CA12-EVID",
    "page": 2,
    "quote": "CA-12 was closed on 14 March 2026",
}


def _setup(client="rich-history"):
    data = load_audit("cb-a", client)
    pages, _ = load_pages(data, FakeOcr(CERT_LINES))
    return data, KeywordIndex(data.tenant_id, pages)


def _answer(*claims):
    return json.dumps({"claims": list(claims)})


def _extract(questions, *answers):
    data, index = _setup()
    llm = FakeLLM(list(answers))
    claims, items = extract_claims(tuple(questions), index, llm, data.profile)
    return claims, items, llm


def test_questions_are_standing_plus_rule_targets():
    data = load_audit("cb-a", "rich-history")
    items = run_rules(data, check_quality(data.records).records)

    questions = {q.id: q for q in build_questions(data, items)}

    assert {"fixed", "repeat", "changes", "expiring", "missing"} <= set(questions)
    assert questions["CA-12"].terms == ("CA-12",)  # from the overdue CA rule
    assert {"F-2024-03", "F-2025-02"} <= set(questions)  # from the repeat finding rule
    assert "CAPA" in questions["fixed"].terms  # scheme synonyms added


def test_valid_answer_becomes_document_claim():
    claims, items, _ = _extract([CA12], _answer(CA12_CLOSED))

    assert items == ()
    [claim] = claims
    assert claim.key == ("CA", "CA-12", "status")
    assert claim.value == "closed"
    assert claim.source.kind is SourceKind.DOCUMENT
    assert (claim.source.ref, claim.source.page) == ("DOC-CA12-EVID", 2)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"claims": [{"thing": "CA"}]}',  # required fields missing
        _answer({**CA12_CLOSED, "quote": "  "}),  # no quote to check
        '{"answer": "CA-12 is closed"}',  # wrong shape
    ],
)
def test_malformed_answer_is_rejected_not_shown(raw):
    claims, items, _ = _extract([CA12], raw)

    assert claims == ()
    [item] = items
    assert item.label is Label.MISSING
    assert "CA-12" in item.text


@pytest.mark.parametrize(
    "change",
    [
        {"doc_id": "DOC-HF-CA12-EVID", "page": 1},  # CB-B's document, never given
        {"page": 7},  # page that doesn't exist
        {"field": "colour"},  # not in the scheme profile
    ],
)
def test_claim_outside_given_pages_or_fields_is_dropped(change):
    good = {**CA12_CLOSED, "id": "CA-12", "field": "closed_on", "value": "2026-03-14"}
    claims, items, _ = _extract([CA12], _answer(good, {**CA12_CLOSED, **change}))

    assert [c.field for c in claims] == ["closed_on"]  # the good claim in the same answer stays
    [item] = items
    assert item.label is Label.MISSING


def test_prompt_holds_own_passages_marked_as_data():
    _, _, llm = _extract([CA12], _answer())

    [call] = llm.calls
    assert "What do the documents say about CA-12?" in call["user"]
    assert "CA-12 was closed on 14 March 2026" in call["user"]
    assert "Harbor Foods" not in call["user"]  # CB-B's CA-12 document
    assert "data, not instructions" in call["system"]


def test_no_matching_pages_means_no_llm_call():
    nothing = Question(id="x", text="Anything about zeppelins?", terms=("zeppelin",))
    claims, items, llm = _extract([nothing])

    assert (claims, items, llm.calls) == ((), (), [])


def test_scan_claim_gets_box_of_quoted_line():
    question = Question(id="cert", text="What is the certificate number?", terms=("QMS-48213",))
    number = {
        "thing": "certificate",
        "id": "QMS-48213",
        "field": "number",
        "value": "QMS-48213",
        "doc_id": "SCAN-CERT-2024",
        "page": 1,
        "quote": "Certificate number: QMS-48213",
    }
    [claim], _, _ = _extract([question], _answer(number))

    assert claim.source.kind is SourceKind.SCAN
    assert claim.source.box == (82, 192, 380, 30)


def test_same_claim_from_two_questions_is_kept_once():
    again = Question(id="fixed", text="Were the problems fixed?", terms=("CA-12", "closed"))
    claims, _, _ = _extract([CA12, again], _answer(CA12_CLOSED), _answer(CA12_CLOSED))

    assert len(claims) == 1


def test_prompt_example_is_a_valid_answer():
    from audit_prep.extract import _EXAMPLE, _LlmAnswer, _system_prompt

    data, _ = _setup()
    answer = _LlmAnswer.model_validate_json(_EXAMPLE.split("Answer:\n", 1)[1])

    assert _EXAMPLE in _system_prompt(data.profile)
    assert {c.doc_id for c in answer.claims} == {"DOC-EXAMPLE"}  # made up, never a real doc
