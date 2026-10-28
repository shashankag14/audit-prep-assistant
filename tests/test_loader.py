"""Loader tests: the right data loads, and nothing crosses tenant or audit lines."""

import shutil

import pytest

from audit_prep.config import DATA_DIR
from audit_prep.loader import ScopeError, load_audit, load_scheme_profile


def test_loads_planned_audit_for_rich_history():
    data = load_audit("cb-a", "rich-history")

    assert data.audit["id"] == "AUD-2026-S2"
    assert data.records["client"]["name"] == "Brightline Components Ltd"
    assert data.profile.scheme == "ISO 9001"


def test_thin_history_has_one_past_audit():
    data = load_audit("cb-a", "thin-history")

    past = [a for a in data.records["audits"] if a["status"] == "completed"]
    assert len(past) == 1
    assert data.records["findings"] == []


def test_cb_a_cannot_load_cb_b_client():
    with pytest.raises(ScopeError):
        load_audit("cb-a", "harbor-foods")


@pytest.mark.parametrize("client_id", ["../../cb-b/clients/harbor-foods", "harbor-foods/", ".."])
def test_path_tricks_are_rejected(client_id):
    with pytest.raises(ScopeError):
        load_audit("cb-a", client_id)


def test_file_tagged_with_other_tenant_is_rejected(tmp_path):
    # A CB-B file copied into CB-A's folder must still not load for CB-A.
    shutil.copytree(DATA_DIR / "scheme_profiles", tmp_path / "scheme_profiles")
    target = tmp_path / "tenants" / "cb-a" / "clients" / "harbor-foods"
    target.mkdir(parents=True)
    shutil.copy(DATA_DIR / "tenants/cb-b/clients/harbor-foods/records.json", target)

    with pytest.raises(ScopeError):
        load_audit("cb-a", "harbor-foods", data_dir=tmp_path)


def test_audit_of_another_client_is_rejected():
    with pytest.raises(ScopeError):
        load_audit("cb-a", "rich-history", audit_id="HF-AUD-2026-S2")


def test_scope_clauses_are_known_to_the_profile():
    # Data sanity: every clause a client is audited on exists in the scheme profile.
    profile = load_scheme_profile("iso9001")
    for client_id in ("rich-history", "thin-history"):
        data = load_audit("cb-a", client_id)
        assert set(data.audit["scope_clauses"]) <= set(profile.clauses)


def test_profile_has_standing_questions_for_surveillance():
    surveillance = load_scheme_profile("iso9001").audit_types["surveillance"]

    assert len(surveillance.standing_questions) >= 5
    assert "internal audit report" in surveillance.expected_documents
