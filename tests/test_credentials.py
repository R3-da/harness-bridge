import json
import sys

import pytest

from hbridge import HBridgeError, credentials
from hbridge.catalog import Catalog


def test_env_beats_opencode_auth(catalog, go_key, monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "from-env")
    assert credentials.require(catalog, "opencode-go") == "from-env"


def test_opencode_auth_fallback(catalog, go_key):
    key, tried = credentials.resolve(catalog, "opencode-go")
    assert key == go_key
    assert tried[-1].startswith("opencode auth.json")


def test_file_and_command_sources(home):
    (home / "k").write_text("file-key\n")
    (home / "catalog.toml").write_text(
        f'''[credentials.openrouter]
sources = [{{ file = "{home}/missing" }}, {{ command = ["{sys.executable}", "-c", "print('cmd-key')"] }}]
[credentials.opencode-go]
sources = [{{ file = "{home}/k" }}]
'''
    )
    catalog = Catalog.load()
    assert credentials.require(catalog, "openrouter") == "cmd-key"
    assert credentials.require(catalog, "opencode-go") == "file-key"


def test_missing_key_lists_sources(catalog):
    with pytest.raises(HBridgeError, match="tried: env OPENROUTER_API_KEY"):
        credentials.require(catalog, "openrouter")
