"""Run the full pipeline on every client in eval/gold.json, score it, write results.

uv run python eval/run.py                        # real model (default 3B), a few minutes on CPU
uv run python eval/run.py --model qwen2.5-1.5b   # faster model -> eval/results-qwen2.5-1.5b.md
uv run python eval/run.py --no-llm               # rules-only baseline -> eval/results-no-llm.md

Prints the results and writes them as markdown next to this file.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from audit_prep import __version__
from audit_prep.cli import make_brief
from audit_prep.config import DATA_DIR, DEFAULT_MODEL, MODELS
from audit_prep.documents import RapidOcr
from audit_prep.evaluate import load_gold, own_doc_ids, report, score
from audit_prep.extract import PROMPT_VERSION
from audit_prep.llm import LlamaCppClient

EVAL_DIR = Path(__file__).parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--no-llm", action="store_true", help="rules-only baseline")
    parser.add_argument("--out", help="results file (default: eval/results*.md)")
    args = parser.parse_args(argv)

    gold = load_gold(EVAL_DIR / "gold.json")
    llm = None if args.no_llm else LlamaCppClient(args.model)
    ocr = RapidOcr()

    results, notices = [], set()
    start = time.monotonic()

    # Run the pipeline on every client in the gold set, score it, and collect notices.
    for g in gold.clients:
        brief, run = make_brief(g.tenant, g.client, None, llm, ocr)

        client_dir = DATA_DIR / "tenants" / g.tenant / "clients" / g.client
        results.append(score(brief, g, own_doc_ids(client_dir), run))
        notices.update(run.notices)

    minutes = (time.monotonic() - start) / 60

    model = "none (rules only)" if llm is None else llm.model_id
    when = f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC"
    header = [
        f"- Run: {when}, audit-prep {__version__}, {minutes:.1f} min",
        f"- Model: {model}, prompt {PROMPT_VERSION}",
        f"- Clients: {', '.join(f'{g.tenant}/{g.client}' for g in gold.clients)}",
        *(f"- Notice: {n}" for n in sorted(notices)),
    ]

    # Write results as markdown
    text = report(results, gold, header)

    name = "results.md"
    if args.no_llm:
        name = "results-no-llm.md"
    elif args.model != DEFAULT_MODEL:
        name = f"results-{args.model}.md"
    out = Path(args.out) if args.out else EVAL_DIR / name
    out.write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]  # Windows: cp1252, no ✓
    print(text)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
