"""Command-line entry point: build the brief for one audit and write it as HTML.

audit-prep --client rich-history            -> out/brief.html (+ out/brief.provenance.json)
audit-prep --client thin-history --model qwen2.5-1.5b --out out/thin.html
audit-prep --client rich-history --no-llm   -> rules-only brief, no model needed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audit_prep import __version__
from audit_prep.checks import record_claims, run_checks
from audit_prep.config import DATA_DIR, DEFAULT_MODEL, MODELS
from audit_prep.documents import KeywordIndex, Ocr, RapidOcr, load_pages
from audit_prep.external import RegistryUnavailable, registry_claims, registry_path
from audit_prep.extract import PROMPT_VERSION, build_questions, extract_claims
from audit_prep.llm import LLM, LlamaCppClient, LLMUnavailable
from audit_prep.loader import ScopeError, load_audit, profile_path
from audit_prep.models import Item, Label
from audit_prep.provenance import RunInfo, save_provenance
from audit_prep.quality import check_quality
from audit_prep.rank import Brief, build_brief
from audit_prep.render import render_html
from audit_prep.rules import run_rules


def make_brief(
    tenant: str,
    client: str,
    audit: str | None,
    llm: LLM | None,
    ocr: Ocr,
    data_dir: Path = DATA_DIR,
) -> tuple[Brief, RunInfo]:
    """Run the whole pipeline for one audit (steps as in docs/03).

    Never fails as a whole when one part is down: no LLM -> rules-only brief,
    no registry -> no external claims. Each skip becomes a notice at the top.
    """

    notices: list[str] = []

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
    hits = [index.search(list(q.terms)) for q in questions]
    asked = sum(1 for h in hits if h)  # questions with matching pages go to the LLM
    sent = dict.fromkeys(f"{h.page.doc_id} p.{h.page.page}" for hs in hits for h in hs)

    claims, extract_items = (), ()
    documents_read = False
    if llm is None:
        notices.append("Documents not read: LLM turned off. This brief is rules only.")
    else:
        try:
            claims, extract_items = extract_claims(questions, index, llm, data.profile)
            documents_read = True
        except LLMUnavailable as e:
            notices.append(f"Documents not read: {e}. This brief is rules only.")

    # Documents were read but nothing came back: say so, don't leave an empty section.
    no_claims = []
    if documents_read and asked and not claims and not extract_items:
        no_claims.append(
            Item(
                label=Label.MISSING,
                text=f"Documents read ({asked} questions asked), but no claims were found",
                why="the model returned nothing for any question; document evidence is unchecked",
                rule="no_claims",
            )
        )

    # Step 4: checks, against record and registry claims.
    external_checked = True
    try:
        external = registry_claims(records, data_dir)
    except RegistryUnavailable as e:
        external, external_checked = (), False
        notices.append(f"External sources not checked: {e}.")
    others = record_claims(records, data.profile) + external

    check_items = run_checks(claims, pages, others)

    # Step 5: rank into sections.
    items = quality.items + rule_items + page_items + extract_items + tuple(no_claims)
    brief = build_brief(data, records, items + check_items)

    # Get only the files this run read: this client's folder, its profile, the registry if it was used.
    client_dir = data_dir / "tenants" / tenant / "clients" / client
    input_files = [p for p in client_dir.rglob("*") if p.is_file()]
    input_files.append(profile_path(data.records["client"]["scheme"], data_dir))
    if external_checked:
        input_files.append(registry_path(data_dir))

    run = RunInfo(
        model_id=llm.model_id if documents_read else None,
        prompt_version=PROMPT_VERSION if documents_read else None,
        scheme_profile=f"{data.profile.id} {data.profile.version}",
        questions_asked=asked if documents_read else 0,
        claims_found=len(claims),
        pages_sent=tuple(sent) if documents_read else (),
        pages_with_claims=tuple(dict.fromkeys(f"{c.source.ref} p.{c.source.page}" for c in claims)),
        documents_read=documents_read,
        external_checked=external_checked,
        notices=tuple(notices),
        input_files=tuple(input_files),
    )
    return brief, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-prep", description=__doc__)
    parser.add_argument("--version", action="version", version=f"audit-prep {__version__}")
    # --tenant stands in for the auditor's login (auth context) in the prototype.
    parser.add_argument("--tenant", default="cb-a", help="certification body (default: cb-a)")
    parser.add_argument("--client", required=True, help="client id, e.g. rich-history")
    parser.add_argument("--audit", help="audit id (default: the planned audit)")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--out", default="out/brief.html", help="where to write the brief")
    parser.add_argument("--no-llm", action="store_true", help="rules-only brief, skip documents")
    args = parser.parse_args(argv)

    llm = None if args.no_llm else LlamaCppClient(args.model)
    try:
        brief, run = make_brief(args.tenant, args.client, args.audit, llm, RapidOcr())
    except ScopeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for notice in run.notices:
        print(f"warning: {notice}", file=sys.stderr)

    client_dir = DATA_DIR / "tenants" / brief.tenant_id / "clients" / brief.client_id
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(brief, client_dir, run), encoding="utf-8")
    save_provenance(out.with_suffix(".provenance.json"), brief, run, DATA_DIR)
    print(f"wrote {out} and {out.with_suffix('.provenance.json').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
