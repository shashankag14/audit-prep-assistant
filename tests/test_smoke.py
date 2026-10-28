import json

from audit_prep.cli import main


def test_cli_prints_rules_only_brief(capsys):
    assert main(["--client", "rich-history"]) == 0

    brief = json.loads(capsys.readouterr().out)
    assert brief["audit"] == "AUD-2026-S2"
    assert brief["items"]


def test_cli_refuses_other_tenant(capsys):
    assert main(["--tenant", "cb-a", "--client", "harbor-foods"]) == 1
    assert "harbor-foods" not in capsys.readouterr().out
