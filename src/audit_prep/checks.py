"""Checks on claims: citation, cross-source. No AI.

Each claim read from a document goes through, in order:

| Step         | Question                                         | If not          |
| ------------ | ------------------------------------------------ | --------------- |
| citation     | is the quote on the cited page (and readable)?   | Missing         |
| cross-source | does every other source give the same value?     | Conflict        |
| (all passed) |                                                  | Extracted       |

Record and registry claims skip the citation check (no quote to check).
Only claims that pass it are compared, so an invented quote can't create or hide a
Conflict. A Conflict shows every source; no check picks a winner.

Not built yet: verifier using Jev style classifier (does a real quote actually support the claim? -> Check source).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from audit_prep.config import CITATION_MIN_RATIO
from audit_prep.documents import Page, low_confidence_lines
from audit_prep.loader import SchemeProfile
from audit_prep.models import Claim, Item, Label, Source, SourceKind

# Where each claim thing lives in the records, and which field is its id.
RECORD_THINGS = {
    "CA": ("corrective_actions", "id"),
    "finding": ("findings", "id"),
    "certificate": ("certificate", "number"),
}


def record_claims(records: dict[str, Any], profile: SchemeProfile) -> tuple[Claim, ...]:
    """Turn the (cleaned) records into claims, for the profile's fields only.

    Example: corrective action CA-12 -> CA · CA-12 · status · open · record CA-12
    Empty or None fields are skipped (quality.py already reported them).
    """

    claims = []
    for thing, (key, id_field) in RECORD_THINGS.items():
        rows = records.get(key) or []
        if isinstance(rows, dict):  # the certificate is one object, not a list
            rows = [rows]
        for row in rows:
            ref = row.get(id_field)
            if not ref:
                continue
            for field in profile.fields.get(thing, ()):
                value = row.get(field)
                if value in (None, ""):
                    continue
                source = Source(kind=SourceKind.RECORD, ref=ref)
                claims.append(
                    Claim(thing=thing, id=ref, field=field, value=str(value), source=source)
                )
    return tuple(claims)


def run_checks(
    doc_claims: tuple[Claim, ...],
    pages: tuple[Page, ...],
    other_claims: tuple[Claim, ...] = (),
) -> tuple[Item, ...]:
    """Label every document claim; compare it with `other_claims` (records, registry)."""

    page_of = {(p.doc_id, p.page): p for p in pages}
    items: list[Item] = []
    passed: list[Claim] = []

    for claim in doc_claims:
        # Step 1: citation. Not found or unreadable -> Missing, claim not used further.
        missing = citation_problem(claim, page_of.get((claim.source.ref, claim.source.page)))
        if missing:
            items.append(missing)
            continue
        passed.append(claim)

    # Step 2: cross-source, over everything that has a value we trust enough to compare.
    return tuple(items + cross_source((*other_claims, *passed)))


def citation_problem(claim: Claim, page: Page | None) -> Item | None:
    """A Missing item if the quote isn't on the cited page, or sits on an unreadable scan line."""

    quote = claim.source.quote or ""
    where = f"{claim.source.ref} p.{claim.source.page}"

    # MISSING LABEL: the quote is not on the cited page (likely invented or reworded by the LLM).
    # `page is None` is a safety net; extract.py already drops claims citing pages it wasn't given.
    if page is None or not quote_on_page(quote, page):
        # No source shown: the quote may be invented, so it must not look like evidence.
        return Item(
            label=Label.MISSING,
            text=f"{_name(claim)}: quote not found in {where}",
            why="the quote could not be found on the cited page, so the claim is not used",
            rule="citation",
        )

    # MISSING LABEL: the quote is on the page, but OCR is not confident on the line holding it.
    if low_confidence_lines(page, quote):
        # Source kept: the box points the auditor at the line to read on the scan.
        return Item(
            label=Label.MISSING,
            text=f"{_name(claim)}: unreadable on {where}",
            why="OCR is not confident on the line holding this value; read it on the scan",
            sources=(claim.source,),
            rule="citation",
        )

    return None


def quote_on_page(quote: str, page: Page, min_ratio: float = CITATION_MIN_RATIO) -> bool:
    """Is the quote on the page? Exact first, then the closest stretch of the same length.

    Ignores case and spacing. On scans all spaces are dropped, because OCR drops them.
    """

    norm = _compact if page.kind is SourceKind.SCAN else _collapse
    q, text = norm(quote), norm(page.text)
    if not q:
        return False
    if q in text:
        return True

    # Slide a window of the quote's length over the page; keep the best match.
    windows = (text[i : i + len(q)] for i in range(max(1, len(text) - len(q) + 1)))
    best = max(SequenceMatcher(None, q, w).ratio() for w in windows)
    return best >= min_ratio


def cross_source(claims: tuple[Claim, ...]) -> list[Item]:
    """Group claims by key. Different values -> Conflict; else non-record claims -> Extracted."""

    groups: dict[tuple[str, str, str], list[Claim]] = {}
    for claim in claims:
        groups.setdefault(claim.key, []).append(claim)

    items = []
    for group in groups.values():
        values = {c.value.strip().lower() for c in group}
        read = [c for c in group if c.source.kind is not SourceKind.RECORD]

        if len(values) > 1:
            says = "; ".join(f"{_where(c.source)} says {c.value}" for c in group)
            items.append(
                Item(
                    label=Label.CONFLICT,
                    text=f"{_name(group[0])}: {says}",
                    why="sources disagree; none is picked",
                    sources=tuple(c.source for c in group),
                    rule="cross_source",
                )
            )
        elif read:
            why = _why_extracted(read[0].source)
            if len(read) < len(group):  # a record gave the same value
                why += "; matches the record"
            items.append(
                Item(
                    label=Label.EXTRACTED,
                    text=f"{_name(read[0])}: {read[0].value}",
                    why=why,
                    sources=tuple(c.source for c in read),
                    rule="extracted",
                )
            )
    return items


def _name(claim: Claim) -> str:
    """How a claim is named in the brief, e.g. "CA-12 status", "supplier evaluation 2026 status"."""

    field = claim.field.replace("_", " ")
    if claim.thing in RECORD_THINGS:
        return f"{claim.id} {field}"
    return f"{claim.thing.replace('_', ' ')} {claim.id} {field}"


def _where(source: Source) -> str:
    if source.kind is SourceKind.RECORD:
        return "record"
    if source.kind is SourceKind.EXTERNAL:
        return source.supplied_by or source.ref
    return f"{source.ref} p.{source.page}"


def _why_extracted(source: Source) -> str:
    if source.kind is SourceKind.EXTERNAL:
        return f"from {source.supplied_by or source.ref}, checked {source.checked_on}"
    return "quote found on the cited page"


def _collapse(text: str) -> str:
    """Lowercase, all whitespace runs -> one space."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _compact(text: str) -> str:
    """Lowercase, no whitespace at all."""
    return re.sub(r"\s+", "", text.lower())
