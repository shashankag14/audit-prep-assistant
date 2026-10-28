from datetime import date

import pytest
from pydantic import ValidationError

from audit_prep.models import Claim, Item, Label, Source, SourceKind

RECORD = Source(kind=SourceKind.RECORD, ref="CA-12")
DOC = Source(kind=SourceKind.DOCUMENT, ref="evidence.pdf", page=2, quote="CA-12 closed 14 Mar")
REGISTRY = Source(
    kind=SourceKind.EXTERNAL, ref="https://registry.example/C-881", checked_on=date(2026, 10, 28)
)


def test_one_item_per_label():
    items = [
        Item(
            label=Label.FACT,
            text="CA-12 open, 41 days overdue",
            why="open CA past due date",
            sources=(RECORD,),
        ),
        Item(
            label=Label.EXTRACTED,
            text="Supplier evaluation postponed",
            why="matches open CA",
            sources=(DOC,),
        ),
        Item(
            label=Label.CHECK_SOURCE,
            text="Evaluation done",
            why="quote may be about 2023",
            sources=(DOC,),
        ),
        Item(
            label=Label.SUGGESTION,
            text="Sample purchasing records",
            why="repeat finding",
            sources=(RECORD, DOC),
        ),
        Item(
            label=Label.CONFLICT,
            text="CA-12 status differs",
            why="document disagrees with record",
            sources=(RECORD, DOC),
        ),
        Item(label=Label.MISSING, text="Internal audit report 2026", why="not submitted"),
    ]
    assert {item.label for item in items} == set(Label)


def test_claims_about_the_same_field_share_a_key():
    from_record = Claim(thing="CA", id="CA-12", field="status", value="open", source=RECORD)
    from_doc = Claim(thing="CA", id="CA-12", field="status", value="closed", source=DOC)
    assert from_record.key == from_doc.key
    assert from_record.value != from_doc.value


@pytest.mark.parametrize(
    "kind, fields",
    [
        (SourceKind.DOCUMENT, {"page": 2}),  # no quote
        (SourceKind.SCAN, {"page": 1, "quote": "valid until 03/2026"}),  # no box
        (SourceKind.EXTERNAL, {}),  # no date checked
    ],
)
def test_source_rejects_missing_provenance(kind, fields):
    with pytest.raises(ValidationError):
        Source(kind=kind, ref="x", **fields)


def test_conflict_needs_two_sources():
    with pytest.raises(ValidationError):
        Item(label=Label.CONFLICT, text="x", why="y", sources=(RECORD,))


def test_fact_needs_a_source():
    with pytest.raises(ValidationError):
        Item(label=Label.FACT, text="x", why="y")


def test_external_source_is_valid_with_link_and_date():
    assert REGISTRY.checked_on == date(2026, 10, 28)
