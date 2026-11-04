import json
import os
import subprocess
import sys
from pathlib import Path

from hbridge import shims, tools
from hbridge.cli import main

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_use_and_status(home, capsys):
    assert main(["use", "codex", "or"]) == 0
    assert main(["status", "codex"]) == 0
    out = capsys.readouterr().out
    assert "codex: openrouter" in out
    assert "openrouter" in out.splitlines()[-1]


def test_use_without_provider_prints_status(home, capsys):
    assert main(["use", "claude"]) == 0
    assert "anthropic" in capsys.readouterr().out


def test_unknown_provider_is_an_error(home, capsys):
    assert main(["use", "codex", "nope"]) == 1
    assert "unknown provider 'nope'" in capsys.readouterr().err


def test_run_parsing(home, capsys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    main(["run", "--print", "kilo", "or", "--", "--help"])
    argv = json.loads(capsys.readouterr().out)["argv"]
    assert argv[1:] == ["-m", "openrouter/deepseek/deepseek-v4.1-flash", "--help"]
    # A first argument that is not a provider belongs to the tool.
    main(["run", "--print", "kilo", "run", "hello"])
    assert json.loads(capsys.readouterr().out)["argv"][1:] == ["run", "hello"]


def test_key_command(home, go_key, capsys):
    assert main(["key", "opencode-go"]) == 0
    assert capsys.readouterr().out == "go-secret\n"


def test_install_and_uninstall_shims(home, capsys):
    target = home / "shim-bin"
    assert main(["install-shims", "--dir", str(target), "--wrap"]) == 0
    names = {p.name for p in target.iterdir()}
    assert {"ccuse", "cxuse", "kuse", "piuse", "huse"} <= names
    assert {"claude-go", "claude-or", "claude-openrouter", "codex-openai", "kilo-go", "pi-or"} <= names
    assert {"claude", "codex"} <= names
    assert 'exec hbridge run codex go -- "$@"' in (target / "codex-go").read_text()
    assert 'exec hbridge use claude "$@"' in (target / "ccuse").read_text()

    (target / "mine").write_text("keep")
    assert main(["uninstall-shims", "--dir", str(target)]) == 0
    assert {p.name for p in target.iterdir()} == {"mine"}


def test_install_refuses_to_clobber_foreign_files(home, capsys):
    target = home / "shim-bin"
    target.mkdir()
    (target / "ccuse").write_text("someone else's script")
    assert main(["install-shims", "--dir", str(target)]) == 1
    assert "not written by hbridge" in capsys.readouterr().err


def test_shims_end_to_end(home, tmp_path):
    """Run a generated shim through a real shell and hbridge process."""
    target = tmp_path / "shim-bin"
    (home / "catalog.toml").write_text(f'[settings]\nself = "{sys.executable} -m hbridge"\n')
    env = {**os.environ, "PYTHONPATH": SRC}
    subprocess.run([sys.executable, "-m", "hbridge", "install-shims", "--dir", str(target)],
                   check=True, env=env, capture_output=True)
    result = subprocess.run([str(target / "cxuse"), "go"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "codex: go" in result.stdout
    result = subprocess.run([str(target / "cxuse")], env=env, capture_output=True, text=True)
    assert "go" in result.stdout


def test_doctor_reports_missing_keys(home, capsys):
    main(["use", "claude", "go"])
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "missing  opencode-go" in out
    assert "problem  claude uses go" in out


def test_install_shims_with_explicit_command(home):
    target = home / "shim-bin"
    assert main(["install-shims", "--dir", str(target), "--command", "/opt/hbridge/bin/hbridge", "codex"]) == 0
    assert {p.name for p in target.iterdir()} == {"cxuse", "codex-openai", "codex-go", "codex-openrouter", "codex-or"}
    assert "exec /opt/hbridge/bin/hbridge run codex go" in (target / "codex-go").read_text()
