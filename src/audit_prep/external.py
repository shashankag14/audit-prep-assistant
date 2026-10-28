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


def registry_claims(records: dict[str, Any], data_dir: Path = DATA_DIR) -> tuple[Claim, ...]:
    """Registry claims about the client's certificate. Empty if it isn't listed."""

    number = (records.get("certificate") or {}).get("number")
    if not number:
        return ()

    # The registry is a JSON file, not an API call (for prototype).
    registry = json.loads((data_dir / "external" / "registry.json").read_text(encoding="utf-8"))
    entry = next((c for c in registry["certificates"] if c["number"] == number), None)
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
