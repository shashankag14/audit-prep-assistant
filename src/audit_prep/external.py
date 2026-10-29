"""Mocked public certificate registry. Production: an API call; here a JSON file.

The client is matched by certificate number (exact match). The registry is public,
so one file serves every tenant, but only the client's own certificate is looked up.
Registry values become claims with an external source and the date checked:
external data is evidence to compare, never a Fact.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from audit_prep.config import DATA_DIR
from audit_prep.models import Claim, Source, SourceKind

REGISTRY_FIELDS = ("status", "expiry_date")  # certificate fields the registry publishes


class RegistryUnavailable(RuntimeError):
    """The registry can't be read (down, missing, broken). The brief says it wasn't checked."""


def registry_path(data_dir: Path = DATA_DIR) -> Path:
    """File standing in for the registry API."""

    return data_dir / "external" / "registry.json"


def registry_claims(records: dict[str, Any], data_dir: Path = DATA_DIR) -> tuple[Claim, ...]:
    """Registry claims about the client's certificate. Empty if it isn't listed.

    Raises RegistryUnavailable if the registry can't be read.
    """

    number = (records.get("certificate") or {}).get("number")
    if not number:
        return ()

    # The registry is a JSON file, not an API call (for prototype).
    try:
        registry = json.loads(registry_path(data_dir).read_text(encoding="utf-8"))
        listed = registry["certificates"]
    except (OSError, ValueError, KeyError) as e:  # missing file, bad JSON, wrong shape
        raise RegistryUnavailable(f"certificate registry could not be read: {e}") from e

    entry = next((c for c in listed if c.get("number") == number), None)
    if entry is None:
        return ()

    # The registry is public, so the source is the same for every tenant. The date checked is when the registry was last updated.
    source = Source(
        kind=SourceKind.EXTERNAL,
        ref=f"{registry['url']}/{number}",
        checked_on=date.fromisoformat(registry["checked_on"]),
        supplied_by="certificate registry",
    )
    return tuple(
        Claim(thing="certificate", id=number, field=field, value=entry[field], source=source)
        for field in REGISTRY_FIELDS
        if entry.get(field)
    )
