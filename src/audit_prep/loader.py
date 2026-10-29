"""Load one audit's data, scoped to one tenant and one client.

Scoping happens here, before any rule, search or LLM call, so nothing outside
the caller's tenant can reach later steps. Three guards:

- ids must be plain names (no "..", no slashes), so a path can't escape the tenant folder!
- every records file must carry the tenant id it is loaded for
- the audit must belong to the loaded client

Not found and not allowed raise the same error, so a caller can't probe
whether another tenant's client exists! (using _SAFE_ID)

Records are returned as raw JSON on purpose: the data quality check (quality.py)
needs to see empty fields and bad dates instead of failing the whole load.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from audit_prep.config import DATA_DIR

# Ids become folder names in a path. Only lowercase letters, digits and "-" are
# allowed, so ".." or "/" can't point the path at another tenant's folder.
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ScopeError(Exception):
    """Requested data is outside the caller's tenant or audit, or does not exist."""


class StandingQuestion(BaseModel):
    """A question asked for every audit of a type, even with no history."""

    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    terms: tuple[str, ...]  # search terms for the keyword index


class ExpectedDocument(BaseModel):
    """A document the client should send before this audit type."""

    model_config = ConfigDict(frozen=True)

    type: str
    only_if: str | None = None  # record list that must be non-empty, e.g. "corrective_actions"


class AuditTypeProfile(BaseModel):
    """Scheme-specific config for one audit type: standing questions and expected documents."""

    model_config = ConfigDict(frozen=True)

    standing_questions: tuple[StandingQuestion, ...]
    expected_documents: tuple[ExpectedDocument, ...]


class SchemeProfile(BaseModel):
    """Scheme-specific config: clauses, term map, claim fields, questions per audit type."""

    model_config = ConfigDict(frozen=True)

    id: str
    scheme: str
    version: str
    clauses: dict[str, str]  # clause number -> title
    terms: dict[str, tuple[str, ...]]  # canonical term -> synonyms used by clients
    fields: dict[str, tuple[str, ...]]  # claim thing -> allowed fields
    audit_types: dict[str, AuditTypeProfile]

class AuditData(BaseModel):
    """Everything later steps may see for one audit. Nothing else is loaded."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    client_id: str
    audit: dict[str, Any]  # the audit being prepared
    records: dict[str, Any]  # raw, checked by quality.py
    profile: SchemeProfile


def profile_path(profile_id: str, data_dir: Path = DATA_DIR) -> Path:
    """File holding one scheme profile."""

    _check_id(profile_id)
    return data_dir / "scheme_profiles" / f"{profile_id}.json"


def load_scheme_profile(profile_id: str, data_dir: Path = DATA_DIR) -> SchemeProfile:
    """Load scheme-specific config for one audit type."""

    path = profile_path(profile_id, data_dir)
    return SchemeProfile.model_validate_json(path.read_text(encoding="utf-8"))


def load_audit(
    tenant_id: str,
    client_id: str,
    audit_id: str | None = None,
    data_dir: Path = DATA_DIR,
) -> AuditData:
    """Load one client's records for one audit. Default audit = the planned one.

    Raises ScopeError if the tenant, client or audit is not found or not allowed.
    """
    _check_id(tenant_id)
    _check_id(client_id)

    path = data_dir / "tenants" / tenant_id / "clients" / client_id / "records.json"
    if not path.is_file():
        raise ScopeError(f"no client {client_id!r} for tenant {tenant_id!r}")

    # Load and check the records file
    records = json.loads(path.read_text(encoding="utf-8"))
    if records.get("tenant_id") != tenant_id:
        # Wrong file in the wrong folder: refuse rather than trust the folder name.
        raise ScopeError(f"records for {client_id!r} are not tagged with tenant {tenant_id!r}")

    # Pick requested audit
    audit = _pick_audit(records.get("audits", []), audit_id)
    if audit is None:
        raise ScopeError(f"no audit {audit_id or '(planned)'!r} for client {client_id!r}")

    profile = load_scheme_profile(records["client"]["scheme"], data_dir)
    return AuditData(
        tenant_id=tenant_id,
        client_id=client_id,
        audit=audit,
        records=records,
        profile=profile,
    )


def _pick_audit(audits: list[dict[str, Any]], audit_id: str | None) -> dict[str, Any] | None:
    """Pick one audit from a list of audits. If audit_id is None, pick the planned one."""

    if audit_id is None:
        planned = [a for a in audits if a.get("status") == "planned"]
        return planned[0] if len(planned) == 1 else None

    return next((a for a in audits if a.get("id") == audit_id), None)


def _check_id(value: str) -> None:
    """Check that a tenant, client or audit id is safe to use in a path."""

    if not _SAFE_ID.match(value):
        raise ScopeError(f"invalid id {value!r}")
