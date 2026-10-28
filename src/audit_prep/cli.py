"""Command-line entry point. For now: rules-only brief as JSON (no documents, no LLM yet)."""

from __future__ import annotations

import argparse
import json
import sys

from audit_prep import __version__
from audit_prep.loader import ScopeError, load_audit
from audit_prep.quality import check_quality
from audit_prep.rules import run_rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-prep", description=__doc__)
    parser.add_argument("--version", action="version", version=f"audit-prep {__version__}")
    # --tenant stands in for the auditor's login (auth context) in the prototype.
    parser.add_argument("--tenant", default="cb-a", help="certification body (default: cb-a)")
    parser.add_argument("--client", required=True, help="client id, e.g. rich-history")
    parser.add_argument("--audit", help="audit id (default: the planned audit)")
    args = parser.parse_args(argv)

    try:
        data = load_audit(args.tenant, args.client, args.audit)
    except ScopeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    quality = check_quality(data.records)

    # quality.items are Missing / Conflict items from the data quality check.
    items = quality.items + run_rules(data, quality.records)

    brief = {
        "tenant": data.tenant_id,
        "client": data.client_id,
        "audit": data.audit["id"],
        "items": [item.model_dump(mode="json", exclude_none=True) for item in items],
    }
    print(json.dumps(brief, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
