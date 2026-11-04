import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hbridge.catalog import Catalog  # noqa: E402

KEY_VARS = [
    "OPENCODE_GO_API_KEY", "OPENCODE_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
    "OPENAI_BASE_URL", "CODEX_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY", "HBRIDGE_CATALOG", "OPENCODE_AUTH_FILE",
]

HERMES_FAKE = """#!/usr/bin/env python3
import json, os, sys
path = os.path.join(os.environ["HERMES_HOME"], "fake.json")
data = json.load(open(path)) if os.path.exists(path) else {}
args = sys.argv[1:]
if args[:2] == ["config", "set"]:
    data[args[2]] = args[3]
    json.dump(data, open(path, "w"))
elif args[:2] == ["config", "get"]:
    print(data.get(args[2], ""))
"""


def _exe(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated HOME with fake harness binaries on PATH."""
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("claude", "codex", "kilo", "pi"):
        _exe(bin_dir / name, "#!/bin/sh\nexit 0\n")
    _exe(bin_dir / "hermes", HERMES_FAKE.replace("/usr/bin/env python3", sys.executable))
    env = {
        "HOME": tmp_path,
        "XDG_CONFIG_HOME": tmp_path / ".config",
        "XDG_STATE_HOME": tmp_path / ".local/state",
        "CLAUDE_CONFIG_DIR": tmp_path / ".claude",
        "CODEX_HOME": tmp_path / ".codex",
        "PI_CODING_AGENT_DIR": tmp_path / ".pi/agent",
        "HERMES_HOME": tmp_path / ".hermes",
    }
    for key, value in env.items():
        Path(value).mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(key, str(value))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setenv("HBRIDGE_CATALOG", str(tmp_path / "catalog.toml"))
    (tmp_path / "catalog.toml").write_text('[settings]\nself = "hbridge"\n')
    return tmp_path


@pytest.fixture
def catalog(home):
    return Catalog.load()


@pytest.fixture
def go_key(home):
    auth = home / ".local/share/opencode/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({"opencode-go": {"type": "api", "key": "go-secret"}}))
    return "go-secret"
