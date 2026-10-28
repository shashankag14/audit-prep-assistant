"""Data quality check on load.

Runs on the raw records before any rule. Returns:

- a cleaned copy of the records: bad values set to None, so a rule never
  computes on them (e.g., an empty due date must not count as "on time")
- one brief item per problem, so the auditor sees what could not be checked

| Problem                              | Item     |
| ------------------------------------ | -------- |
| required field empty                 | Missing  |
| date impossible or wrong format      | Missing  |
| record points to something unknown   | Missing  |
| duplicate records that disagree      | Conflict |

Duplicates (same id) are merged into one row. Fields the copies agree on are kept,
so rules can still use them; fields they disagree on become None (no side picked).
"""

from __future__ import annotations

import copy
import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from audit_prep.models import Item, Label, Source, SourceKind

# record list -> (thing name used in claims, required fields)
_REQUIRED = {
    "audits": ("audit", ("id", "type", "date", "status")),
    "findings": ("finding", ("id", "audit_id", "clause", "grade")),
    "corrective_actions": ("CA", ("id", "finding_id", "status", "due_date")),
    "submitted_documents": ("document", ("id", "type", "received_on")),
}
_CERT_REQUIRED = ("number", "status", "expiry_date")

_DATE_FIELDS = {"date", "due_date", "closed_on", "issued_on", "expiry_date", "received_on"}
_DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# field -> record list it must point into
_LINKS = {"audit_id": "audits", "finding_id": "findings"}

_WHY = "data quality check on load; rules that need this field are skipped"


class QualityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    records: dict[str, Any]  # cleaned copy; the input is not changed
    items: tuple[Item, ...]  # Missing / Conflict items for the brief


def check_quality(raw: dict[str, Any]) -> QualityResult:
    records = copy.deepcopy(raw)
    items: list[Item] = []

    for list_name, (thing, required) in _REQUIRED.items():
        # Deduplicate the list, then check each row for empty required fields and bad dates.
        rows, disputed = _dedupe(records.get(list_name, []), thing, items)

        # Check each row for empty required fields and bad dates. Skip fields already reported as Conflict.
        for i, row in enumerate(rows):
            ref = row.get("id") or f"{list_name}[{i}]"
            _check_row(row, thing, ref, required, items, skip=disputed.get(ref, set()))
        records[list_name] = rows

    # Check the certificate, if present, for empty required fields and bad dates.
    cert = records.get("certificate")
    if cert:
        _check_row(cert, "certificate", cert.get("number") or "certificate", _CERT_REQUIRED, items)

    # Check that each link field points to a known record in the target list. If not, report it as Missing and blank the field.
    _check_links(records, items)

    return QualityResult(records=records, items=tuple(items))


def _check_row(
    row: dict[str, Any],
    thing: str,
    ref: str,
    required: tuple[str, ...],
    items: list[Item],
    skip: set[str] | None = None,
) -> None:
    """Flag empty required fields and bad dates. `skip`: fields already reported as Conflict."""
    skip = skip or set()
    for field in required:
        if field not in skip and _is_empty(row.get(field)):
            items.append(_missing(thing, ref, field, "is empty"))
            row[field] = None

    # Optional dates (e.g. closed_on on an open CA) may be empty, but never malformed.
    for field in _DATE_FIELDS & row.keys():
        value = row[field]
        if value is not None and not _is_valid_date(value):
            items.append(_missing(thing, ref, field, f"is not a valid date ({value!r})"))
            row[field] = None


def _dedupe(
    rows: list[dict[str, Any]], thing: str, items: list[Item]
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    """Merge rows with the same id into one. Returns the rows and, per id, the disputed fields.

    Agreed fields keep their value. Disputed fields become None and get one Conflict item.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    no_id: list[dict[str, Any]] = []

    # Group rows by id, and keep track of those with no id.
    for row in rows:
        if row.get("id"):
            groups.setdefault(row["id"], []).append(row)
        else:
            no_id.append(row)  # reported as "id is empty" by _check_row

    # Merge each group into one row, and report any disagreements as Conflict items.
    merged: list[dict[str, Any]] = []
    disputed: dict[str, set[str]] = {}

    for rid, group in groups.items():
        fields = {k for row in group for k in row if row.get(k) != group[0].get(k)}
        merged.append({k: (None if k in fields else v) for row in group for k, v in row.items()})
        if not fields:
            continue  # identical copies: nothing to report

        disputed[rid] = fields
        items.append(
            Item(
                label=Label.CONFLICT,
                text=f"{thing} {rid}: duplicate records disagree on {', '.join(sorted(fields))}",
                why="data quality check on load; none of the copies is picked",
                sources=tuple(
                    Source(kind=SourceKind.RECORD, ref=f"{rid} (copy {n})")
                    for n in range(1, len(group) + 1)
                ),
            )
        )

    # Return the merged rows plus those with no id, and the disputed fields per id.
    return merged + no_id, disputed


def _check_links(records: dict[str, Any], items: list[Item]) -> None:
    known = {name: {row.get("id") for row in records[name]} for name in _LINKS.values()}

    # Check that each link field points to a known record in the target list. If not, report it as Missing and blank the field.
    for list_name, (thing, _) in _REQUIRED.items():
        for row in records[list_name]:
            for field, target in _LINKS.items():
                value = row.get(field)

                # If the field is not empty, it must point to a known record in the target list.
                if value and value not in known[target]:
                    ref = row.get("id") or list_name
                    items.append(_missing(thing, ref, field, f"points to unknown {value!r}"))
                    row[field] = None


def _missing(thing: str, ref: str, field: str, problem: str) -> Item:
    return Item(
        label=Label.MISSING,
        text=f"{thing} {ref}: {field} {problem}",
        why=_WHY,
        sources=(Source(kind=SourceKind.RECORD, ref=ref),),
    )


def _is_empty(value: Any) -> bool:
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == []


def _is_valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not _DATE_SHAPE.match(value):
        return False
    try:
        date.fromisoformat(value)  # catches impossible dates like 2026-02-30
    except ValueError:
        return False
    return True
