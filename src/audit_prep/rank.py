"""Sort items into the brief's sections, in a fixed order. No AI.

| Section                      | Items                   |
| ---------------------------- | ----------------------- |
| Needs attention              | Conflict, Fact          |
| Worth a look                 | Extracted, Check source |
| Not sampled in last 2 audits | the not_sampled Fact    |
| What I could not check       | Missing                 |

Inside a section: by label (in the order above), then in the order the steps made
them. Same data, same brief.

Not built in the prototype: Suggestions (rules over other items, e.g. repeat finding
+ document on the same topic -> "consider sampling more 8.4 records").
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from audit_prep.loader import AuditData
from audit_prep.models import Item, Label

# Definition of the brief's sections, and the order of labels within them.
NEEDS_ATTENTION = "Needs attention"
WORTH_A_LOOK = "Worth a look"
NOT_SAMPLED = "Not sampled in last 2 audits"
COULD_NOT_CHECK = "What I could not check"

SECTION_TITLES = (NEEDS_ATTENTION, WORTH_A_LOOK, NOT_SAMPLED, COULD_NOT_CHECK)
LABEL_ORDER = (
    Label.CONFLICT,
    Label.FACT,
    Label.EXTRACTED,
    Label.CHECK_SOURCE,
    Label.SUGGESTION,
    Label.MISSING,
)
_SECTION_OF_LABEL = {
    Label.CONFLICT: NEEDS_ATTENTION,
    Label.FACT: NEEDS_ATTENTION,
    Label.EXTRACTED: WORTH_A_LOOK,
    Label.CHECK_SOURCE: WORTH_A_LOOK,
    Label.SUGGESTION: WORTH_A_LOOK,
    Label.MISSING: COULD_NOT_CHECK,
}


class Section(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    items: tuple[Item, ...]


class Brief(BaseModel):
    """Everything the renderer needs: who and what the brief is for, and the sections."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    client_id: str
    client_name: str
    scheme: str
    audit: dict[str, Any]
    sections: tuple[Section, ...]


def build_brief(data: AuditData, records: dict[str, Any], items: tuple[Item, ...]) -> Brief:
    """Place every item in its section, in a fixed order."""

    # the same item from two steps is shown once
    unique = list(dict.fromkeys(items))

    sections = []
    for title in SECTION_TITLES:
        chosen = [i for i in unique if section_of(i) == title]
        chosen.sort(key=lambda i: LABEL_ORDER.index(i.label))  # stable: keeps step order
        sections.append(Section(title=title, items=tuple(chosen)))

    return Brief(
        tenant_id=data.tenant_id,
        client_id=data.client_id,
        client_name=(records.get("client") or {}).get("name") or data.client_id,
        scheme=data.profile.scheme,
        audit=data.audit,
        sections=tuple(sections),
    )


def section_of(item: Item) -> str:
    if item.rule == "not_sampled" and item.label is Label.FACT:
        return NOT_SAMPLED
    return _SECTION_OF_LABEL[item.label]
