"""Ranking tests: sections by label, fixed order."""

from audit_prep.loader import load_audit
from audit_prep.models import Item, Label, Source, SourceKind
from audit_prep.quality import check_quality
from audit_prep.rank import (
    COULD_NOT_CHECK,
    NEEDS_ATTENTION,
    NOT_SAMPLED,
    WORTH_A_LOOK,
    build_brief,
)
from audit_prep.rules import run_rules

RECORD = (Source(kind=SourceKind.RECORD, ref="CA-12"),)
DOC = Source(
    kind=SourceKind.DOCUMENT, ref="DOC-MR-2026", page=2, quote="supplier evaluation postponed"
)
POSTPONED = Item(
    label=Label.EXTRACTED,
    text="supplier evaluation 2026 status: postponed",
    why="quote found on the cited page",
    sources=(DOC,),
    rule="extracted",
)


def _rich():
    data = load_audit("cb-a", "rich-history")
    records = check_quality(data.records).records
    return data, records, run_rules(data, records)


def _sections(brief):
    return {s.title: s.items for s in brief.sections}


def test_items_go_to_sections_by_label():
    data, records, rule_items = _rich()
    conflict = Item(
        label=Label.CONFLICT, text="c", why="w", sources=RECORD + (DOC,), rule="cross_source"
    )
    sections = _sections(build_brief(data, records, (*rule_items, conflict)))

    assert [s for s in sections] == [NEEDS_ATTENTION, WORTH_A_LOOK, NOT_SAMPLED, COULD_NOT_CHECK]
    assert sections[NEEDS_ATTENTION][0] is conflict  # Conflict before Facts
    assert {i.label for i in sections[NEEDS_ATTENTION][1:]} == {Label.FACT}
    assert [i.rule for i in sections[NOT_SAMPLED]] == ["not_sampled"]
    assert all(i.label is Label.MISSING for i in sections[COULD_NOT_CHECK])


def test_extracted_goes_to_worth_a_look():
    data, records, rule_items = _rich()
    worth = _sections(build_brief(data, records, (*rule_items, POSTPONED)))[WORTH_A_LOOK]
    assert worth == (POSTPONED,)


def test_same_item_twice_is_shown_once():
    data, records, _ = _rich()
    brief = build_brief(data, records, (POSTPONED, POSTPONED))
    assert _sections(brief)[WORTH_A_LOOK] == (POSTPONED,)
