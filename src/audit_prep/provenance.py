"""What produced a brief, saved next to it as JSON (<brief>.provenance.json).

Lets anyone answer later: which data, which model and prompt, which profile, and
exactly which values and quotes the brief cited. Also lists what was skipped
(LLM off, registry down), so a rules-only brief is never mistaken for a full one.

| Field            | Example                                    |
| ---------------- | ------------------------------------------ |
| model            | Qwen/Qwen2.5-3B-Instruct-GGUF/...gguf, or null (LLM not used) |
| prompt_version   | extract-v2                                 |
| scheme_profile   | iso9001 2015                               |
| pages_sent       | pages given to the LLM, e.g. "DOC-CA12-EVID p.2"   |
| pages_with_claims| pages the LLM's usable claims cite         |
| inputs           | records.json -> sha256, docs/.../p2.txt -> sha256, registry |
| notices          | "Documents not read: ..."                  |
| items            | every brief item with its sources (ref, page, quote) |
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from audit_prep import __version__
from audit_prep.rank import Brief


class RunInfo(BaseModel):
    """How one brief was made. Shown in the brief (banners, footer) and saved as provenance."""

    model_config = ConfigDict(frozen=True)

    model_id: str | None  # None: documents were not read by an LLM
    prompt_version: str | None
    scheme_profile: str  # e.g. "iso9001 2015"
    questions_asked: int = 0  # questions that had matching pages, so went to the LLM
    claims_found: int = 0
    pages_sent: tuple[str, ...] = ()  # pages given to the LLM, e.g. "DOC-CA12-EVID p.2"
    pages_with_claims: tuple[str, ...] = ()  # pages the LLM's usable claims cite
    documents_read: bool = True
    external_checked: bool = True
    notices: tuple[str, ...] = ()  # shown as banners at the top of the brief
    # Files this run read; hashed into provenance "inputs", not saved as a list.
    input_files: tuple[Path, ...] = Field(default=(), exclude=True)


def provenance(brief: Brief, run: RunInfo, inputs: dict[str, str]) -> dict:
    """Provenance as a JSON-ready dict. `inputs` maps file name -> sha256 (see `hash_inputs`)."""

    return {
        "tool": f"audit-prep {__version__}",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tenant": brief.tenant_id,
        "client": brief.client_id,
        "audit": brief.audit.get("id"),
        **run.model_dump(mode="json"),
        "inputs": inputs,
        "items": [
            {"section": s.title, **i.model_dump(mode="json", exclude_none=True)}
            for s in brief.sections
            for i in s.items
        ],
    }


def hash_inputs(files: tuple[Path, ...], data_dir: Path) -> dict[str, str]:
    """sha256 of each file the run read, keyed by its path inside data_dir (for prototype)"""

    return {
        p.relative_to(data_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
    }


def save_provenance(path: Path, brief: Brief, run: RunInfo, data_dir: Path) -> None:
    record = provenance(brief, run, hash_inputs(run.input_files, data_dir))
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
