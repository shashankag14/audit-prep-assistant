"""Eval scoring: the gold set matches what the pipeline makes, and misses are counted.

The pipeline runs with a fake LLM and fake OCR; the real eval is eval/run.py.
"""

import json
from pathlib import Path

from audit_prep.cli import make_brief
from audit_prep.config import DATA_DIR
from audit_prep.documents import OcrLine
from audit_prep.evaluate import (
    ClientGold,
    Expect,
    load_gold,
    own_doc_ids,
    report,
    score,
    stage,
)
from audit_prep.models import Item, Label, Source, SourceKind
from audit_prep.provenance import RunInfo
from audit_prep.rank import Brief, Section
from fakes import FakeOcr

GOLD = load_gold(Path(__file__).parents[1] / "eval" / "gold.json")

SCAN_LINES = [
    OcrLine(text="Certificatenumber:QMS-48213", confidence=0.99, box=(82, 192, 380, 30)),
    OcrLine(text="Valid until: 01 December 2027", confidence=0.62, box=(79, 429, 360, 30)),
]

# What a model that reads correctly would return, by page.
ON_PAGE = {
    ("DOC-CA12-EVID", 2): ("CA", "CA-12", "status", "closed", "CA-12 was closed on 14 March 2026"),
    ("DOC-MR-2026", 2): (
        "supplier_evaluation",
        "2026",
        "status",
        "postponed",
        "The annual supplier evaluation has been postponed to Q3 2026",
    ),
    ("SCAN-CERT-2024", 1): (
        "certificate",
        "QMS-48213",
        "expiry_date",
        "2027-12-01",
        "Valid until: 01 December 2027",
    ),
}


class GoodLLM:
    model_id = "fake/good"

    def complete_json(self, system, user, schema):
        claims = [
            dict(zip(("thing", "id", "field", "value", "quote"), c, strict=True))
            | {"doc_id": doc, "page": page}
            for (doc, page), c in ON_PAGE.items()
            if f'doc="{doc}" page="{page}"' in user
        ]
        return json.dumps({"claims": claims})


def _run_all(llm):
    results = []
    for g in GOLD.clients:
        brief, run = make_brief(g.tenant, g.client, None, llm, FakeOcr(SCAN_LINES))
        client_dir = DATA_DIR / "tenants" / g.tenant / "clients" / g.client
        results.append(score(brief, g, own_doc_ids(client_dir), run))
    return results


def test_good_reader_catches_every_planted_issue():
    results = _run_all(GoodLLM())

    missed = [(r.gold.client, e.what) for r in results for e, i, _ in r.found if i is None]
    assert missed == []
    for r in results:
        assert (r.wrong_claims, r.unexpected_conflicts, r.leaks) == ([], [], [])
    text = report(results, GOLD, [])
    assert "| Planted issues caught | 8/8 | 8/8 |" in text
    assert "| yes | sent ✓ · claim ✓ · brief ✓ |" in text  # stage column for #3, #5, #8


def test_rules_only_misses_the_document_issues():
    results = _run_all(None)

    missed = {e.issue: s for r in results for e, i, s in r.found if i is None}
    assert missed == {3: "LLM off", 5: "LLM off", 8: "LLM off"}  # need a document read


def _brief(*items):
    return Brief(
        tenant_id="cb-a",
        client_id="c",
        client_name="c",
        scheme="ISO 9001",
        audit={},
        sections=(Section(title="all", items=items),),
    )


def test_wrong_claim_and_leak_are_counted():
    doc = Source(kind=SourceKind.DOCUMENT, ref="DOC-HF-CA12-EVID", page=1, quote="CA-12 was closed")
    wrong = Item(label=Label.EXTRACTED, text="CA-12 closed on: 2025-12-01", why="", sources=(doc,))
    gold = ClientGold(
        tenant="cb-a",
        client="c",
        expected=(Expect(issue=1, what="x", label=Label.FACT, text="never"),),
        correct_claims=("CA-12 closed on: 2026-03-14",),
    )

    result = score(_brief(wrong), gold, own_docs={"DOC-CA12-EVID"}, run=_run())

    assert result.found[0][1] is None
    assert result.wrong_claims == [wrong]
    assert result.leaks == [wrong]  # cites another client's document


def _run(sent=(), claimed=()):
    return RunInfo(
        model_id="fake",
        prompt_version="v",
        scheme_profile="p",
        pages_sent=sent,
        pages_with_claims=claimed,
    )


def test_stage_says_where_a_document_issue_stopped():
    e = Expect(issue=3, what="x", label=Label.CONFLICT, text="x", page="DOC-A p.2")
    item = Item(label=Label.MISSING, text="x", why="")

    assert stage(e, None, _run()) == "sent ✗"  # search never found the page
    assert stage(e, None, _run(sent=("DOC-A p.2",))) == "sent ✓ · claim ✗"  # model silent
    assert stage(e, None, _run(("DOC-A p.2",), ("DOC-A p.2",))) == "sent ✓ · claim ✓ · brief ✗"
    assert stage(e, item, _run(("DOC-A p.2",), ("DOC-A p.2",))) == "sent ✓ · claim ✓ · brief ✓"
    assert stage(e.model_copy(update={"page": None}), None, _run()) == ""  # rule issue: no stage
