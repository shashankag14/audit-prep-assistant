"""Score briefs against the planted-issue gold set (eval/gold.json). No AI here.

| Result           | How it is decided                                                  |
| ---------------- | ------------------------------------------------------------------ |
| caught           | an item matches the expected label, rule, text (regex) and source |
| wrong claim      | Extracted item not in the gold list of correct claims             |
| unexpected       | Conflict / Missing / Fact that no expected item asked for          |
| leak             | a document source from outside this client's own folder           |

For document issues the gold set names the page, and the stage says how far it got:
sent to the LLM -> the LLM returned a usable claim citing it -> right item in the brief.

The runner is eval/run.py; this module only scores, so tests can use it with fakes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from audit_prep.models import Item, Label, SourceKind
from audit_prep.provenance import RunInfo
from audit_prep.rank import Brief


class Expect(BaseModel):
    """One item the brief must contain."""

    model_config = ConfigDict(frozen=True)

    issue: int | None = None  # planted issue number; None = expected, but not a planted issue
    what: str
    label: Label
    text: str  # regex on the item text, case-insensitive
    rule: str | None = None
    source: str | None = None  # must be part of one source ref
    page: str | None = None  # document issues: the page holding it, e.g. "DOC-CA12-EVID p.2"

    def matches(self, item: Item) -> bool:
        return (
            item.label is self.label
            and (self.rule is None or item.rule == self.rule)
            and re.search(self.text, item.text, re.IGNORECASE) is not None
            and (self.source is None or any(self.source in s.ref for s in item.sources))
        )


class ClientGold(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant: str
    client: str
    expected: tuple[Expect, ...] = ()
    correct_claims: tuple[str, ...] = ()  # regexes: Extracted items that are right


class Gold(BaseModel):
    model_config = ConfigDict(frozen=True)

    clients: tuple[ClientGold, ...]
    not_in_eval: dict[str, str] = {}  # planted issue number -> why it is not scored


@dataclass
class ClientResult:
    gold: ClientGold
    found: list[tuple[Expect, Item | None, str]]  # expected, matching item, stage
    wrong_claims: list[Item] = field(default_factory=list)
    unexpected_conflicts: list[Item] = field(default_factory=list)
    unneeded_missing: list[Item] = field(default_factory=list)
    other_facts: list[Item] = field(default_factory=list)
    leaks: list[Item] = field(default_factory=list)


def load_gold(path: Path) -> Gold:
    return Gold.model_validate_json(path.read_text(encoding="utf-8"))


def own_doc_ids(client_dir: Path) -> set[str]:
    """Doc ids in this client's folder: the only documents its brief may cite."""

    return {p.name for sub in ("docs", "scans") for p in (client_dir / sub).glob("*") if p.is_dir()}


def score(brief: Brief, gold: ClientGold, own_docs: set[str], run: RunInfo) -> ClientResult:
    """Match the brief's items against the gold set for one client."""

    items = [i for s in brief.sections for i in s.items]
    found = []
    for e in gold.expected:
        item = next((i for i in items if e.matches(i)), None)
        found.append((e, item, stage(e, item, run)))
    matched = {id(i) for _, i, _ in found if i is not None}
    rest = [i for i in items if id(i) not in matched]

    def correct(item: Item) -> bool:
        return any(re.search(p, item.text, re.IGNORECASE) for p in gold.correct_claims)

    return ClientResult(
        gold=gold,
        found=found,
        wrong_claims=[i for i in rest if i.label is Label.EXTRACTED and not correct(i)],
        unexpected_conflicts=[i for i in rest if i.label is Label.CONFLICT],
        unneeded_missing=[i for i in rest if i.label is Label.MISSING],
        other_facts=[i for i in rest if i.label is Label.FACT],
        leaks=[
            i
            for i in items
            if any(
                s.kind in (SourceKind.DOCUMENT, SourceKind.SCAN) and s.ref not in own_docs
                for s in i.sources
            )
        ],
    )


def stage(expect: Expect, item: Item | None, run: RunInfo) -> str:
    """How far a document issue got. Empty for rule and registry issues (no LLM step)."""

    if expect.page is None:
        return ""
    if not run.documents_read:
        return "LLM off"
    steps = [
        ("sent", expect.page in run.pages_sent),
        ("claim", expect.page in run.pages_with_claims),
        ("brief", item is not None),
    ]
    out = []
    for name, ok in steps:
        out.append(f"{name} {'✓' if ok else '✗'}")
        if not ok:
            break  # later steps can't happen
    return " · ".join(out)


def report(results: list[ClientResult], gold: Gold, header: list[str]) -> str:
    """results.md: metrics, then each planted issue, then every item that needs a look."""

    planted = [
        (r.gold.client, e, i, s) for r in results for e, i, s in r.found if e.issue is not None
    ]
    caught = sum(1 for _, _, i, _ in planted if i is not None)
    total = lambda name: sum(len(getattr(r, name)) for r in results)  # noqa: E731

    lines = ["# Eval results", "", *header, ""]
    lines += [
        "| Metric | Target | Result |",
        "| --- | --- | --- |",
        f"| Planted issues caught | {len(planted)}/{len(planted)} | {caught}/{len(planted)} |",
        f"| Wrong claims shown as Extracted | 0 | {total('wrong_claims')} |",
        f"| Unexpected Conflicts | 0 | {total('unexpected_conflicts')} |",
        f"| Unneeded Missing | low | {total('unneeded_missing')} |",
        f"| Cross-tenant leaks | 0 | {total('leaks')} |",
        "",
        "## Planted issues",
        "",
        "Stage (document issues): sent to the LLM → usable claim citing the page → in the brief.",
        "",
        "| # | Client | Expected | Caught | Stage | Brief says |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for client, e, item, st in sorted(planted, key=lambda p: p[1].issue or 0):
        said = _cell(item.text) if item else ""
        mark = "yes" if item else "**no**"
        lines.append(f"| {e.issue} | {client} | {e.label}: {e.what} | {mark} | {st} | {said} |")

    if gold.not_in_eval:
        lines += ["", "Not scored:", ""]
        lines += [f"- #{n}: {why}" for n, why in gold.not_in_eval.items()]

    for title, name in (
        ("Wrong claims (Extracted, not in gold)", "wrong_claims"),
        ("Unexpected Conflicts", "unexpected_conflicts"),
        ("Unneeded Missing", "unneeded_missing"),
        ("Facts not in gold", "other_facts"),
        ("Leaks", "leaks"),
    ):
        rows = [(r.gold.client, i) for r in results for i in getattr(r, name)]
        if rows:
            lines += ["", f"## {title}", ""]
            lines += [f"- {client}: {_cell(i.text)} ({_refs(i)})" for client, i in rows]

    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    """Item text made safe for one markdown table cell."""
    return text.replace("|", "/").replace("\n", " ")


def _refs(item: Item) -> str:
    refs = [f"{s.ref} p.{s.page}" if s.page else s.ref for s in item.sources]
    return ", ".join(refs) or "no source"
