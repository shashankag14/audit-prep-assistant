"""Graceful degradation and provenance: a part going down never breaks the whole brief."""

import json

import pytest

from audit_prep import cli
from audit_prep.documents import OcrLine
from audit_prep.external import RegistryUnavailable, registry_claims
from audit_prep.llm import LLMUnavailable
from fakes import FakeOcr

CERT_LINES = [
    OcrLine(text="Certificatenumber:QMS-48213", confidence=0.99, box=(82, 192, 380, 30)),
]
CA12_CLOSED = {
    "thing": "CA",
    "id": "CA-12",
    "field": "status",
    "value": "closed",
    "doc_id": "DOC-CA12-EVID",
    "page": 2,
    "quote": "CA-12 was closed on 14 March 2026",
}


class ScriptLLM:
    """Gives `claims` whenever the CA-12 evidence page is in the prompt, else nothing."""

    model_id = "fake/script-llm"

    def __init__(self, claims=()):
        self.claims = list(claims)

    def complete_json(self, system, user, schema):
        found = 'doc="DOC-CA12-EVID" page="2"' in user
        return json.dumps({"claims": self.claims if found else []})


class BrokenLLM:
    model_id = "fake/broken"

    def complete_json(self, system, user, schema):
        raise LLMUnavailable("could not load fake/broken: no network")


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Run the CLI with a given LLM; return (html, provenance dict)."""
    monkeypatch.setattr(cli, "RapidOcr", lambda: FakeOcr(CERT_LINES))

    def _run(llm=None, *flags):
        monkeypatch.setattr(cli, "LlamaCppClient", lambda model: llm)
        out = tmp_path / "brief.html"
        assert cli.main(["--client", "rich-history", "--out", str(out), *flags]) == 0
        prov = json.loads(out.with_suffix(".provenance.json").read_text(encoding="utf-8"))
        return out.read_text(encoding="utf-8"), prov

    return _run


def test_llm_off_still_produces_brief(run):
    html, prov = run(None, "--no-llm")

    assert "Documents not read: LLM turned off" in html  # banner
    assert "CA-12 open, 231 days overdue (clause 8.4)" in html  # rules still there
    assert "AI-read" not in html
    assert prov["model_id"] is None and prov["documents_read"] is False


def test_model_that_fails_to_load_gives_rules_only_brief(run):
    html, prov = run(BrokenLLM())

    assert "Documents not read: could not load fake/broken" in html
    assert "Internal audit report not submitted" in html
    assert prov["documents_read"] is False


def test_registry_down_is_said_not_hidden(run, monkeypatch):
    def down(records, data_dir):
        raise RegistryUnavailable("certificate registry could not be read: timeout")

    monkeypatch.setattr(cli, "registry_claims", down)
    html, prov = run(None, "--no-llm")

    assert "External sources not checked" in html
    assert "suspended" not in html  # no registry claim, so no registry Conflict
    assert prov["external_checked"] is False
    assert "external/registry.json" not in prov["inputs"]  # not used, so not hashed


def test_missing_registry_file_raises(tmp_path):
    with pytest.raises(RegistryUnavailable):
        registry_claims({"certificate": {"number": "QMS-48213"}}, data_dir=tmp_path)


def test_empty_answers_are_not_silent(run):
    html, prov = run(ScriptLLM(claims=[]))

    assert "but no claims were found" in html
    assert prov["claims_found"] == 0 and prov["questions_asked"] > 0


def test_provenance_has_versions_inputs_and_cited_quotes(run):
    _, prov = run(ScriptLLM(claims=[CA12_CLOSED]))

    assert prov["model_id"] == "fake/script-llm"
    assert prov["prompt_version"] == "extract-v2"
    assert prov["scheme_profile"] == "iso9001 2015"
    assert "tenants/cb-a/clients/rich-history/records.json" in prov["inputs"]
    assert not any("cb-b" in path for path in prov["inputs"])  # only this client's files
    shared = {p for p in prov["inputs"] if not p.startswith("tenants/")}
    assert shared == {"scheme_profiles/iso9001.json", "external/registry.json"}  # only those used
    assert "input_files" not in prov  # paths show up only as hashed inputs
    quotes = [s.get("quote") for i in prov["items"] for s in i.get("sources", [])]
    assert "CA-12 was closed on 14 March 2026" in quotes
