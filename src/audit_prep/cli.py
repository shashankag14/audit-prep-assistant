"""Command-line entry point: build the brief for one audit and write it as HTML.

audit-prep --client rich-history            -> out/brief.html
audit-prep --client thin-history --model qwen2.5-1.5b --out out/thin.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audit_prep import __version__
from audit_prep.checks import record_claims, run_checks
from audit_prep.config import DATA_DIR, DEFAULT_MODEL, MODELS
from audit_prep.documents import KeywordIndex, Ocr, RapidOcr, load_pages
from audit_prep.external import registry_claims
from audit_prep.extract import build_questions, extract_claims
from audit_prep.llm import LLM, LlamaCppClient, LLMUnavailable
from audit_prep.loader import ScopeError, load_audit
from audit_prep.quality import check_quality
from audit_prep.rank import Brief, build_brief
from audit_prep.render import render_html
from audit_prep.rules import run_rules


def make_brief(
    tenant: str,
    client: str,
    audit: str | None,
    llm: LLM,
    ocr: Ocr,
    data_dir: Path = DATA_DIR,
) -> Brief:
    """Run the whole pipeline for one audit (steps as in docs/03)."""

    # Step 1: load, scoped to one tenant and client, and check data quality.
    data = load_audit(tenant, client, audit, data_dir)
    quality = check_quality(data.records)
    records = quality.records

    # Step 2: rules on records -> Facts / Missing.
    rule_items = run_rules(data, records)

    # Step 3: pages (OCR for scans), keyword index, LLM reads the passages -> claims.
    pages, page_items = load_pages(data, ocr, data_dir)
    index = KeywordIndex(data.tenant_id, pages)
    questions = build_questions(data, rule_items)
    claims, extract_items = extract_claims(questions, index, llm, data.profile)

    # Step 4: checks, against record and registry claims.
    others = record_claims(records, data.profile) + registry_claims(records, data_dir)
    check_items = run_checks(claims, pages, others)

    # Step 5: rank into sections.
    items = quality.items + rule_items + page_items + extract_items + check_items
    return build_brief(data, records, items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-prep", description=__doc__)
    parser.add_argument("--version", action="version", version=f"audit-prep {__version__}")
    # --tenant stands in for the auditor's login (auth context) in the prototype.
    parser.add_argument("--tenant", default="cb-a", help="certification body (default: cb-a)")
    parser.add_argument("--client", required=True, help="client id, e.g. rich-history")
    parser.add_argument("--audit", help="audit id (default: the planned audit)")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--out", default="out/brief.html", help="where to write the brief")
    args = parser.parse_args(argv)

    try:
        brief = make_brief(
            args.tenant, args.client, args.audit, LlamaCppClient(args.model), RapidOcr()
        )
    except ScopeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except LLMUnavailable as e:  # no rules-only fallback yet
        print(f"error: {e}", file=sys.stderr)
        return 1

    client_dir = DATA_DIR / "tenants" / brief.tenant_id / "clients" / brief.client_id
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(brief, client_dir), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
