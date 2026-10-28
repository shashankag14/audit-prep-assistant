"""Rules on records: Facts and Missing, no AI.

Rules read the cleaned records from quality.py. A None field was already
reported there, so a rule that needs it skips silently (no double items).
All dates are judged against the planned audit date, not today, so the
same data always gives the same brief.

The rules below encode the generic surveillance questions ("Were last time's problems
fixed?", "Is anything failing again?", "What's missing?")
These hold for any certification body and any scheme, so they are not in the scheme profile.

| Rule              | Label   | Needs                     |
| ----------------- | ------- | ------------------------- |
| overdue_ca        | Fact    | audit date                |
| expiring_cert     | Fact    | audit date                |
| repeat_finding    | Fact    | 2+ past audits            |
| not_sampled       | Fact    | 2+ past audits, scope     |
| missing_document  | Missing | profile for the audit type|
| thin_history      | Missing | fewer than 2 past audits  |
"""

from __future__ import annotations

from datetime import date
from typing import Any

from audit_prep.loader import AuditData, SchemeProfile
from audit_prep.models import Item, Label, Source, SourceKind

# Could be tenant specific, but for now it's the same for all tenants and schemes.
MIN_PAST_AUDITS = 2  # history-based rules need at least this many completed audits
EXPIRY_WARNING_DAYS = 90  # certificate expiring within this many days of the audit


def run_rules(data: AuditData, records: dict[str, Any]) -> tuple[Item, ...]:
    """Run every rule for the audit in `data` on the cleaned `records`."""

    # The audit date is required for several rules.
    # If it's missing, the rules that need it are skipped.
    audit = next(a for a in records["audits"] if a.get("id") == data.audit["id"])
    audit_date = _as_date(audit.get("date"))
    past = sorted(
        (a for a in records["audits"] if a.get("status") == "completed" and a.get("date")),
        key=lambda a: a["date"],
    )

    # Run the rules that need the audit date, then the history-based rules,
    # then the profile-based rules.
    items: list[Item] = []
    if audit_date:
        items += overdue_cas(records, audit_date)
        items += expiring_certificate(records, audit_date)

    # Run the history-based rules. If there are too few past audits,
    # report that and skip the other history-based rules.
    if len(past) < MIN_PAST_AUDITS:
        items.append(thin_history(past))
    else:
        items += repeat_findings(records, past)
        items += not_sampled(audit, past[-2:], data.profile)

    items += missing_documents(records, audit, data.profile)
    return tuple(items)


def overdue_cas(records: dict[str, Any], audit_date: date) -> list[Item]:
    """Corrective actions that are not closed and whose due date is before the audit date."""

    clause_of = {f["id"]: f.get("clause") for f in records["findings"]}
    items = []

    for ca in records["corrective_actions"]:
        # Skip closed CAs, those with no due date, and those not yet due.
        due = _as_date(ca.get("due_date"))
        if ca.get("status") == "closed" or due is None or due >= audit_date:
            continue

        # If the CA is linked to a finding, include the clause in the item text.
        clause = clause_of.get(ca.get("finding_id"))
        on_clause = f" (clause {clause})" if clause else ""

        # Item becomes a FACT. Report the CA as overdue,
        # with the number of days overdue in the text.
        items.append(
            _fact(
                f"{ca['id']} open, {(audit_date - due).days} days overdue{on_clause}",
                why=f"not closed and due date {due} is before the audit",
                refs=[ca["id"]],
                rule="overdue_ca",
            )
        )
    return items


def expiring_certificate(records: dict[str, Any], audit_date: date) -> list[Item]:
    """Certificate expiring within EXPIRY_WARNING_DAYS of the audit date."""

    cert = records.get("certificate") or {}
    expiry = _as_date(cert.get("expiry_date"))
    if expiry is None:
        return []

    # If the certificate is expiring more than EXPIRY_WARNING_DAYS after the audit,
    # it's not reported.
    days = (expiry - audit_date).days
    if days > EXPIRY_WARNING_DAYS:
        return []

    # Report the certificate as expiring, with the number of days until expiry in the text.
    text = f"Certificate {cert.get('number')} " + (
        f"expired {-days} days before the audit"
        if days < 0
        else f"expires {days} days after the audit"
    )

    # Item becomes a FACT with a why that explains the rule and a reference to the certificate.
    return [
        _fact(
            text,
            why=f"expiry date {expiry} is within {EXPIRY_WARNING_DAYS} days of the audit",
            refs=[cert.get("number") or "certificate"],
            rule="expiring_cert",
        )
    ]


def repeat_findings(records: dict[str, Any], past: list[dict[str, Any]]) -> list[Item]:
    """Same clause found in two or more past audits."""

    # Build a mapping from audit id to year, and a mapping from clause to
    # the findings on that clause in the past audits.
    year_of = {a["id"]: a["date"][:4] for a in past}
    by_clause: dict[str, list[dict[str, Any]]] = {}
    for f in records["findings"]:
        if f.get("clause") and f.get("audit_id") in year_of:
            by_clause.setdefault(f["clause"], []).append(f)

    # For each clause with findings in two or more audits, report a FACT with the clause,
    # the years of the audits, and the finding ids as references.
    items = []
    for clause, findings in sorted(by_clause.items(), key=lambda kv: _clause_key(kv[0])):
        audits = {f["audit_id"] for f in findings}
        if len(audits) < 2:
            continue
        years = " and ".join(sorted(year_of[a] for a in audits))
        items.append(
            _fact(
                f"Clause {clause} finding repeated in {years}",
                why=f"findings on the same clause in {len(audits)} audits",
                refs=[f["id"] for f in findings],
                rule="repeat_finding",
            )
        )
    return items


def not_sampled(
    audit: dict[str, Any], last_two: list[dict[str, Any]], profile: SchemeProfile
) -> list[Item]:
    """Clauses in this audit's scope that neither of the last two audits sampled."""

    scope = audit.get("scope_clauses") or []
    if not scope:
        return [
            Item(
                label=Label.MISSING,
                text=f"Audit {audit['id']}: scope clauses not recorded",
                why="can't tell which clauses were not sampled recently",
                rule="not_sampled",
            )
        ]

    # Build a set of clauses sampled in the last two audits, then find the clauses
    # in this audit's scope that were not sampled in either of the last two audits.
    sampled = {c for a in last_two for c in a.get("clauses_sampled") or []}
    gaps = sorted(set(scope) - sampled, key=_clause_key)
    if not gaps:
        return []

    # If there are gaps, report a FACT with the clauses and the last two audits as references.
    # The text includes the clause numbers and their descriptions from the scheme profile.
    names = ", ".join(f"{c} {profile.clauses.get(c, '')}".strip() for c in gaps)
    return [
        _fact(
            f"Not sampled in the last 2 audits: {names}",
            why=f"in this audit's scope, not sampled in {' or '.join(a['id'] for a in last_two)}",
            refs=[a["id"] for a in last_two],
            rule="not_sampled",
        )
    ]


def missing_documents(
    records: dict[str, Any], audit: dict[str, Any], profile: SchemeProfile
) -> list[Item]:
    """Documents expected by the scheme profile for this audit type that were not submitted."""

    # If the audit type is not in the scheme profile, report a Missing item
    # and skip the other document checks.
    audit_type = profile.audit_types.get(audit.get("type") or "")
    if audit_type is None:
        return [
            Item(
                label=Label.MISSING,
                text=f"No {profile.scheme} profile for audit type {audit.get('type')!r}",
                why="expected documents and standing questions are unknown",
                rule="missing_document",
            )
        ]

    # Check each expected document for this audit type. If it is not in the submitted
    # documents, report a Missing item with the document type and the reason from the profile.
    submitted = {d.get("type") for d in records["submitted_documents"]}

    return [
        Item(
            label=Label.MISSING,
            text=f"{doc.type.capitalize()} not submitted",
            why=f"expected before a {audit['type']} audit ({profile.scheme} profile)",
            rule="missing_document",
        )
        for doc in audit_type.expected_documents
        if doc.type not in submitted and (doc.only_if is None or records.get(doc.only_if))
    ]


def thin_history(past: list[dict[str, Any]]) -> Item:
    """Fewer than MIN_PAST_AUDITS completed audits in the history."""

    return Item(
        label=Label.MISSING,
        text=f"Not enough history: {len(past)} past audit(s)",
        why=(
            f"repeat-finding and not-sampled checks need {MIN_PAST_AUDITS} past audits; "
            "only the standing questions are used"
        ),
        sources=tuple(Source(kind=SourceKind.RECORD, ref=a["id"]) for a in past),
        rule="thin_history",
    )


def _fact(text: str, why: str, refs: list[str], rule: str) -> Item:
    """Return a FACT item with the given text, why, and references."""

    sources = tuple(Source(kind=SourceKind.RECORD, ref=r) for r in refs)
    return Item(label=Label.FACT, text=text, why=why, sources=sources, rule=rule)


def _as_date(value: str | None) -> date | None:
    """Convert an ISO date string to a date object, or return None if the value is None."""

    return date.fromisoformat(value) if value else None


def _clause_key(clause: str) -> tuple[int, ...]:
    """Sort clauses by number, so 10.2 comes after 9.3."""

    return tuple(int(part) for part in clause.split(".") if part.isdigit())
