"""Core data shapes shared by every step of the pipeline.

Two ideas from docs/03-ai-system-design.md live here:

- Every source (records, documents, scans, external data) becomes a `Claim`
  with the same shape: thing · id · field · value · source. One generic
  cross-source check can then compare any two claims.
- Every line in the brief is an `Item` with exactly one `Label`. The label
  says what kind of evidence the item rests on; there is no confidence score.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class Label(StrEnum):
    """What kind of statement a brief item is (see docs/02, "Labels")."""

    FACT = "Fact"  # computed by a rule from records
    EXTRACTED = "Extracted"  # read from a document or external source, quote found
    CHECK_SOURCE = "Check source"  # quote is real, but may not support the claim
    SUGGESTION = "Suggestion"  # a hint built by a rule from other items
    CONFLICT = "Conflict"  # two or more sources disagree; none is picked
    MISSING = "Missing"  # absent, unreadable, or could not be verified


class SourceKind(StrEnum):
    RECORD = "record"  # structured data from the auditee's system, e.g. a database record
    DOCUMENT = "document"  # a document (PDF, Word, etc.) that is read and quoted (unstructured)
    SCAN = "scan"  # a scanned document (image) that is read and quoted (unstructured)
    # a link to an external source (web page, API, etc.) that is checked and quoted
    EXTERNAL = "external"


class Source(BaseModel):
    """Where a claim came from. What must be filled depends on the kind.

    | kind     | required                         |
    | -------- | -------------------------------- |
    | record   | ref (record id)                  |
    | document | ref (doc id), page, quote        |
    | scan     | ref (doc id), page, quote, box   |
    | external | ref (link), checked_on           |
    """

    model_config = ConfigDict(frozen=True)

    kind: SourceKind
    ref: str
    version: str | None = None
    page: int | None = None
    quote: str | None = None
    box: tuple[int, int, int, int] | None = None  # x, y, width, height on the scan
    checked_on: date | None = None
    supplied_by: str | None = None  # e.g. "auditee", "certification body"

    @model_validator(mode="after")
    def _required_fields_for_kind(self) -> Source:
        needed = {
            SourceKind.RECORD: [],
            SourceKind.DOCUMENT: ["page", "quote"],
            SourceKind.SCAN: ["page", "quote", "box"],
            SourceKind.EXTERNAL: ["checked_on"],
        }[self.kind]

        missing = [name for name in needed if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.kind} source needs: {', '.join(missing)}")

        return self


class Claim(BaseModel):
    """One statement about one field of one thing, from one source.

    Example: CA | CA-12 | status | open | record CA-12
    """

    model_config = ConfigDict(frozen=True)

    thing: str  # e.g. "CA", "certificate", "finding"
    id: str  # e.g. "CA-12"
    field: str  # from the fixed field list in the scheme profile
    value: str
    source: Source

    @property
    def key(self) -> tuple[str, str, str]:
        """Claims with the same key talk about the same thing and can be compared."""
        return (self.thing, self.id, self.field)


class Item(BaseModel):
    """One line in the brief: a label, what it says, why it is there, and its sources."""

    model_config = ConfigDict(frozen=True)

    label: Label
    text: str
    why: str
    sources: tuple[Source, ...] = ()
    rule: str | None = None  # which rule or check made it, e.g. "overdue_ca"; used for ranking

    @model_validator(mode="after")
    def _sources_match_label(self) -> Item:
        if self.label is Label.CONFLICT and len(self.sources) < 2:
            raise ValueError("a Conflict must show at least two sources")

        if self.label not in (Label.MISSING, Label.CONFLICT) and not self.sources:
            # Missing may have nothing to point at (e.g. a document never submitted).
            raise ValueError(f"a {self.label} item must cite at least one source")

        return self
