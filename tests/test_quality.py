"""Data quality tests: bad values become gaps in the brief, never inputs to a rule."""

import copy

from audit_prep.loader import load_audit
from audit_prep.models import Label
from audit_prep.quality import check_quality


def _records(**overrides):
    """Small valid records; overrides replace whole lists."""
    records = {
        "audits": [
            {"id": "A1", "type": "surveillance", "date": "2025-11-11", "status": "completed"}
        ],
        "findings": [{"id": "F1", "audit_id": "A1", "clause": "8.4", "grade": "minor"}],
        "corrective_actions": [
            {"id": "CA-1", "finding_id": "F1", "status": "open", "due_date": "2026-03-31"}
        ],
        "certificate": {"number": "QMS-1", "status": "valid", "expiry_date": "2027-12-01"},
        "submitted_documents": [],
    }
    records.update(overrides)
    return records


def test_clean_records_give_no_items():
    assert check_quality(_records()).items == ()


def test_ca_with_empty_due_date_is_a_gap_not_on_time():
    # Planted in rich-history: CA-13 has an empty due date.
    result = check_quality(load_audit("cb-a", "rich-history").records)

    assert [i.text for i in result.items] == ["CA CA-13: due_date is empty"]
    assert result.items[0].label is Label.MISSING

    cas = {ca["id"]: ca for ca in result.records["corrective_actions"]}
    assert cas["CA-13"]["due_date"] is None  # no rule can call it "on time"
    assert cas["CA-12"]["due_date"] == "2026-03-31"  # good values untouched


def test_other_clients_are_clean():
    for tenant, client in [("cb-a", "thin-history"), ("cb-b", "harbor-foods")]:
        assert check_quality(load_audit(tenant, client).records).items == ()


def test_bad_dates_are_gaps():
    cas = [
        {"id": "CA-1", "finding_id": "F1", "status": "open", "due_date": "2026-02-30"},
        {"id": "CA-2", "finding_id": "F1", "status": "open", "due_date": "31/03/2026"},
    ]
    result = check_quality(_records(corrective_actions=cas))

    assert {i.label for i in result.items} == {Label.MISSING}
    assert len(result.items) == 2
    assert all(ca["due_date"] is None for ca in result.records["corrective_actions"])


def test_empty_optional_date_is_fine():
    cas = [
        {
            "id": "CA-1",
            "finding_id": "F1",
            "status": "open",
            "due_date": "2026-03-31",
            "closed_on": None,
        }
    ]
    assert check_quality(_records(corrective_actions=cas)).items == ()


def test_identical_duplicates_are_merged():
    finding = {"id": "F1", "audit_id": "A1", "clause": "8.4", "grade": "minor"}
    result = check_quality(_records(findings=[finding, dict(finding)]))

    assert result.items == ()
    assert len(result.records["findings"]) == 1


def test_disagreeing_duplicates_are_a_conflict_and_disputed_field_is_blanked():
    findings = [
        {"id": "F1", "audit_id": "A1", "clause": "8.4", "grade": "minor"},
        {"id": "F1", "audit_id": "A1", "clause": "8.4", "grade": "major"},
    ]
    result = check_quality(_records(findings=findings))

    # One Conflict only: the blanked grade is not reported again as "empty".
    [item] = result.items
    assert item.label is Label.CONFLICT
    assert "grade" in item.text
    assert len(item.sources) == 2

    # One merged row: agreed clause kept for the rules, disputed grade picks no side.
    [finding] = result.records["findings"]
    assert finding["clause"] == "8.4"
    assert finding["grade"] is None


def test_link_to_unknown_record_is_a_gap():
    cas = [{"id": "CA-1", "finding_id": "F-404", "status": "open", "due_date": "2026-03-31"}]
    result = check_quality(_records(corrective_actions=cas))

    [item] = result.items
    assert item.label is Label.MISSING
    assert "F-404" in item.text


def test_input_is_not_changed():
    raw = _records(
        corrective_actions=[{"id": "CA-1", "finding_id": "F1", "status": "open", "due_date": ""}]
    )
    before = copy.deepcopy(raw)
    check_quality(raw)
    assert raw == before
