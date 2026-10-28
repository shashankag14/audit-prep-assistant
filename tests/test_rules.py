"""Rule tests: one per rule, on the real synthetic data where it is planted, else small records."""

from datetime import date

from audit_prep.loader import load_audit, load_scheme_profile
from audit_prep.models import Label
from audit_prep.quality import check_quality
from audit_prep.rules import (
    expiring_certificate,
    missing_documents,
    not_sampled,
    overdue_cas,
    run_rules,
)

AUDIT_DAY = date(2026, 11, 17)


def _brief(tenant, client):
    data = load_audit(tenant, client)
    return {item.rule: item for item in run_rules(data, check_quality(data.records).records)}


def _records(**overrides):
    records = {
        "audits": [],
        "findings": [],
        "corrective_actions": [],
        "certificate": {},
        "submitted_documents": [],
    }
    records.update(overrides)
    return records


# --- planted in rich-history ---


def test_overdue_ca_is_a_fact():
    item = _brief("cb-a", "rich-history")["overdue_ca"]
    assert item.label is Label.FACT
    assert item.text == "CA-12 open, 231 days overdue (clause 8.4)"


def test_repeat_finding_is_a_fact():
    item = _brief("cb-a", "rich-history")["repeat_finding"]
    assert item.text == "Clause 8.4 finding repeated in 2024 and 2025"
    assert {s.ref for s in item.sources} == {"F-2024-03", "F-2025-02"}


def test_not_sampled_lists_scope_minus_last_two_audits():
    item = _brief("cb-a", "rich-history")["not_sampled"]
    assert "7.1.5" in item.text and "8.7" in item.text
    assert "8.4" not in item.text


def test_missing_internal_audit_report():
    item = _brief("cb-a", "rich-history")["missing_document"]
    assert item.label is Label.MISSING
    assert item.text == "Internal audit report not submitted"


# --- planted in thin-history ---


def test_thin_history_is_missing_and_skips_history_rules():
    brief = _brief("cb-a", "thin-history")
    assert brief["thin_history"].label is Label.MISSING
    assert "repeat_finding" not in brief and "not_sampled" not in brief


def test_ca_evidence_not_expected_without_cas():
    data = load_audit("cb-a", "thin-history")
    texts = [i.text for i in missing_documents(data.records, data.audit, data.profile)]
    assert "Corrective action evidence not submitted" not in texts


# --- small records ---


def test_empty_due_date_is_never_on_time_or_overdue():
    # quality.py blanks the bad value and reports it; the rule stays silent.
    cas = [{"id": "CA-1", "status": "open", "due_date": None}]
    assert overdue_cas(_records(corrective_actions=cas), AUDIT_DAY) == []


def test_closed_and_not_yet_due_cas_are_not_overdue():
    cas = [
        {"id": "CA-1", "status": "closed", "due_date": "2026-01-01"},
        {"id": "CA-2", "status": "open", "due_date": "2026-12-31"},
    ]
    assert overdue_cas(_records(corrective_actions=cas), AUDIT_DAY) == []


def test_certificate_expiring_soon_is_a_fact():
    cert = {"number": "QMS-1", "expiry_date": "2027-01-10"}
    [item] = expiring_certificate(_records(certificate=cert), AUDIT_DAY)
    assert item.label is Label.FACT
    assert item.text == "Certificate QMS-1 expires 54 days after the audit"


def test_certificate_far_from_expiry_gives_nothing():
    cert = {"number": "QMS-1", "expiry_date": "2028-01-10"}
    assert expiring_certificate(_records(certificate=cert), AUDIT_DAY) == []


def test_unknown_scope_is_missing_not_silent():
    profile = load_scheme_profile("iso9001")
    [item] = not_sampled({"id": "A9"}, [], profile)
    assert item.label is Label.MISSING
