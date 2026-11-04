import json
import tomllib

import pytest

from hbridge import HBridgeError, tools


# --- Claude Code -----------------------------------------------------------

def test_claude_switch_round_trip(home, catalog):
    path = home / ".claude/settings.json"
    path.write_text(json.dumps({"model": "opus", "env": {"KEEP": "1", "ANTHROPIC_API_KEY": "stale"}}))
    claude = tools.get(catalog, "cc")

    claude.set("go")
    settings = json.loads(path.read_text())
    assert settings["model"] == "opus"
    assert settings["env"]["KEEP"] == "1"
    assert "ANTHROPIC_API_KEY" not in settings["env"]
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://opencode.ai/inference/go/anthropic"
    assert settings["apiKeyHelper"] == "hbridge key opencode-go"
    assert claude.status().provider == "go"

    claude.set("anthropic")
    settings = json.loads(path.read_text())
    assert settings["env"] == {"KEEP": "1"}
    assert "apiKeyHelper" not in settings
    assert claude.status().provider == "anthropic"


def test_claude_keeps_foreign_api_key_helper(home, catalog):
    path = home / ".claude/settings.json"
    path.write_text(json.dumps({"apiKeyHelper": "my-own-helper"}))
    tools.get(catalog, "claude").set("anthropic")
    assert json.loads(path.read_text())["apiKeyHelper"] == "my-own-helper"


def test_claude_one_shot_injects_token(home, catalog, go_key, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "inherited")
    launch = tools.get(catalog, "claude").launch("go", ["-p", "hi"])
    assert launch.argv[1:] == ["-p", "hi"]
    assert launch.env["ANTHROPIC_AUTH_TOKEN"] == go_key
    assert launch.env["ANTHROPIC_BASE_URL"].startswith("https://opencode.ai")
    assert "ANTHROPIC_API_KEY" not in launch.env


def test_claude_default_launch_follows_settings(home, catalog, go_key):
    claude = tools.get(catalog, "claude")
    claude.set("go")
    launch = claude.launch(None, [])
    assert launch.env["ANTHROPIC_AUTH_TOKEN"] == go_key
    claude.set("anthropic")
    assert "ANTHROPIC_AUTH_TOKEN" not in claude.launch(None, []).env


def test_one_shot_without_key_fails(home, catalog):
    with pytest.raises(HBridgeError, match="no key found"):
        tools.get(catalog, "claude").launch("openrouter", [])


# --- Codex -----------------------------------------------------------------

CODEX_CONFIG = '''# my comment
model = "gpt-5.4"
model_provider = "openai"
model_reasoning_effort = "high"
developer_instructions = """
[not a table]
"""
model = "dup-written-by-desktop-app"

[model_providers.openrouter]
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"
env_key = "OPENROUTER_API_KEY"

[tui]
theme = "dark"
'''


def test_codex_switch_preserves_file_and_adds_missing_provider(home, catalog):
    path = home / ".codex/config.toml"
    path.write_text(CODEX_CONFIG)
    codex = tools.get(catalog, "cx")

    codex.set("go")
    text = path.read_text()
    config = tomllib.loads(text)
    assert "# my comment" in text
    assert config["model"] == "deepseek-v4.1-flash"
    assert config["model_provider"] == "opencode_go"
    assert config["model_reasoning_effort"] == "high"
    assert config["tui"]["theme"] == "dark"
    go = config["model_providers"]["opencode_go"]
    assert go["base_url"] == "https://opencode.ai/zen/go/v1"
    assert go["auth"] == {"command": "hbridge", "args": ["key", "opencode-go"]}
    assert codex.status().provider == "go"

    codex.set("openrouter")
    config = tomllib.loads(path.read_text())
    # The user's own table is left alone.
    assert config["model_providers"]["openrouter"]["env_key"] == "OPENROUTER_API_KEY"
    assert "auth" not in config["model_providers"]["openrouter"]
    assert path.read_text().count("[model_providers.opencode_go]") == 1

    codex.set(codex.resolve("sub"))
    config = tomllib.loads(path.read_text())
    assert (config["model"], config["model_provider"]) == ("gpt-5.4", "openai")


def test_codex_creates_config_when_missing(home, catalog):
    tools.get(catalog, "codex").set("go")
    config = tomllib.loads((home / ".codex/config.toml").read_text())
    assert config["model_provider"] == "opencode_go"


def test_codex_status_defaults_to_subscription(home, catalog):
    assert tools.get(catalog, "codex").status().provider == "openai"


def test_codex_one_shot_flags_precede_subcommand(home, catalog, go_key, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "would-beat-the-login")
    launch = tools.get(catalog, "codex").launch("go", ["exec", "hi"])
    argv = launch.argv[1:]
    assert argv[-2:] == ["exec", "hi"]
    assert argv[argv.index("-m") + 1] == "deepseek-v4.1-flash"
    assert "model_provider=opencode_go" in argv
    # The provider table is passed inline because config.toml lacks it.
    inline = next(a for a in argv if a.startswith("model_providers.opencode_go="))
    assert 'base_url = "https://opencode.ai/zen/go/v1"' in inline
    assert "OPENAI_API_KEY" not in launch.env
    # And the file was not touched.
    assert not (home / ".codex/config.toml").exists()


def test_codex_default_launch_unsets_api_keys(home, catalog, monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "x")
    launch = tools.get(catalog, "codex").launch(None, ["resume"])
    assert launch.argv[1:] == ["resume"]
    assert "CODEX_API_KEY" not in launch.env


# --- Kilo ------------------------------------------------------------------

def test_kilo_switch_updates_config_and_state(home, catalog):
    config = home / ".config/kilo/kilo.jsonc"
    config.parent.mkdir(parents=True)
    config.write_text('{"model": "openai/gpt-5.4", "mcp": {"x": {}}}')
    kilo = tools.get(catalog, "k")

    kilo.set("go")
    data = json.loads(config.read_text())
    assert data["model"] == "opencode-go/deepseek-v4.1-flash"
    assert data["small_model"] == "opencode-go/glm-5.3-flash"
    assert data["mcp"] == {"x": {}}
    state = json.loads((home / ".local/state/kilo/model.json").read_text())
    assert state["model"]["code"] == {"providerID": "opencode-go", "modelID": "deepseek-v4.1-flash"}
    assert state["recent"][0]["providerID"] == "opencode-go"
    status = kilo.status()
    assert (status.provider, status.detail) == ("go", "opencode-go/deepseek-v4.1-flash")


def test_kilo_jsonc_comments_are_backed_up(home, catalog):
    config = home / ".config/kilo/kilo.jsonc"
    config.parent.mkdir(parents=True)
    config.write_text('{\n  // keep me\n  "model": "openai/gpt-5.4", "url": "http://x//y",\n}\n')
    message = tools.get(catalog, "kilo").set("openrouter")
    assert "comments were dropped" in message
    assert "// keep me" in (config.parent / "kilo.jsonc.bak").read_text()
    data = json.loads(config.read_text())
    assert data["url"] == "http://x//y"
    assert data["model"].startswith("openrouter/")


def test_kilo_status_recognises_other_models_by_prefix(home, catalog):
    state = home / ".local/state/kilo/model.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"model": {"code": {"providerID": "opencode-go", "modelID": "glm-5.3"}}}))
    status = tools.get(catalog, "kilo").status()
    assert (status.provider, status.detail) == ("go", "opencode-go/glm-5.3")


def test_kilo_one_shot(home, catalog, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    launch = tools.get(catalog, "kilo").launch("openrouter", ["run", "x"])
    assert launch.argv[1:] == ["-m", "openrouter/deepseek/deepseek-v4.1-flash", "run", "x"]
    assert launch.env["OPENROUTER_API_KEY"] == "or-key"


# --- Pi --------------------------------------------------------------------

def test_pi_switch_and_one_shot(home, catalog, go_key):
    path = home / ".pi/agent/settings.json"
    path.write_text(json.dumps({"theme": "dark"}))
    pi = tools.get(catalog, "pi")
    pi.set("go")
    settings = json.loads(path.read_text())
    assert settings == {
        "theme": "dark",
        "defaultProvider": "opencode-go",
        "defaultModel": "deepseek-v4.1-flash",
        "enabledModels": ["opencode-go/deepseek-v4.1-flash"],
    }
    assert pi.status().provider == "go"

    launch = pi.launch("go", [])
    assert launch.argv[1:] == [
        "--provider", "opencode-go", "--models", "opencode-go/deepseek-v4.1-flash",
        "--model", "deepseek-v4.1-flash", "--api-key", go_key,
    ]
    assert launch.env["OPENCODE_API_KEY"] == go_key


def test_pi_subscription_one_shot_drops_other_keys(home, catalog, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    launch = tools.get(catalog, "pi").launch("openai", [])
    assert "--api-key" not in launch.argv
    assert "OPENROUTER_API_KEY" not in launch.env


def test_pi_default_launch_exports_available_keys(home, catalog, go_key):
    launch = tools.get(catalog, "pi").launch(None, [])
    assert launch.argv[1:] == []
    assert launch.env["OPENCODE_API_KEY"] == go_key


# --- Hermes ----------------------------------------------------------------

def test_hermes_uses_its_own_config_command(home, catalog, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    hermes = tools.get(catalog, "h")
    hermes.set("openrouter")
    data = json.loads((home / ".hermes/fake.json").read_text())
    assert data == {"model.provider": "openrouter", "model.default": "deepseek/deepseek-v4.1-flash"}
    assert hermes.status().provider == "openrouter"
    launch = hermes.launch("openrouter", ["chat"])
    assert launch.argv[1:] == ["--provider", "openrouter", "-m", "deepseek/deepseek-v4.1-flash", "chat"]


# --- shared behaviour ------------------------------------------------------

def test_writes_go_through_symlinks(home, catalog):
    repo = home / "dotfiles"
    repo.mkdir()
    real = repo / "settings.json"
    real.write_text("{}")
    link = home / ".claude/settings.json"
    link.symlink_to(real)
    tools.get(catalog, "claude").set("openrouter")
    assert link.is_symlink()
    assert "openrouter.ai" in real.read_text()


def test_binary_lookup_skips_shims(home, catalog):
    shim_dir = home / "shims"
    shim_dir.mkdir()
    shim = shim_dir / "codex"
    shim.write_text(f"#!/bin/sh\n{tools.SHIM_MARKER}\nexec hbridge run codex\n")
    shim.chmod(0o755)
    env = {"PATH": f"{shim_dir}:{home / 'bin'}"}
    assert tools.which("codex", env) == str(home / "bin/codex")


def test_unconfigured_harnesses_say_so(home, catalog):
    assert tools.get(catalog, "pi").status() == tools.Status(None, tools.NOT_CONFIGURED)
    assert tools.get(catalog, "kilo").status() == tools.Status(None, tools.NOT_CONFIGURED)
    assert tools.get(catalog, "hermes").status() == tools.Status(None, tools.NOT_CONFIGURED)
