import pytest

from audit_prep.cli import main


def test_cli_prints_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("audit-prep ")


def test_cli_refuses_other_tenant(capsys):
    assert main(["--tenant", "cb-a", "--client", "harbor-foods"]) == 1
    assert "harbor-foods" not in capsys.readouterr().out
