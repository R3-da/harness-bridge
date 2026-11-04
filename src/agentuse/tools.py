"""One adapter per harness: where its config lives, how to switch it, how to launch it."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentuse import AgentuseError, credentials
from agentuse.catalog import Catalog
from agentuse.files import (
    atomic_write,
    codex_lines,
    expand,
    jsonc_has_comments,
    parse_toml,
    read_json,
    set_top_level,
    toml_table,
    toml_value,
    write_json,
)

SHIM_MARKER = "# agentuse-shim"


def _xdg(name: str, fallback: str) -> Path:
    return expand(os.environ.get(name) or fallback)


def is_shim(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return SHIM_MARKER.encode() in handle.read(512)
    except OSError:
        return False


def which(binary: str, env: dict[str, str]) -> str | None:
    """Find a binary on PATH, skipping agentuse's own wrapper shims."""
    if os.sep in binary:
        path = expand(binary)
        return str(path) if os.access(path, os.X_OK) else None
    for directory in (env.get("PATH") or os.defpath).split(os.pathsep):
        candidate = Path(directory or ".") / binary
        if candidate.is_file() and os.access(candidate, os.X_OK) and not is_shim(candidate):
            return str(candidate)
    return None


def self_command(catalog: Catalog) -> list[str]:
    """How config files should invoke agentuse (for `agentuse key ...`)."""
    configured = catalog.settings.get("self")
    if configured:
        return shlex.split(configured) if isinstance(configured, str) else list(configured)
    found = shutil.which("agentuse")
    if found and not is_shim(Path(found)):
        return [os.path.abspath(found)]
    return [sys.executable, "-m", "agentuse"]


@dataclass
class Launch:
    argv: list[str]
    env: dict[str, str]


@dataclass
class Status:
    provider: str | None  # catalog provider key, or None when unrecognised
    detail: str  # model or raw value, for display


class Tool:
    name = ""

    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.spec = catalog.tool(self.name)

    # -- configuration ------------------------------------------------------

    def default_config(self) -> Path:
        raise NotImplementedError

    def config_path(self) -> Path:
        configured = self.spec.get("config")
        return expand(configured) if configured else self.default_config()

    def provider_spec(self, provider: str) -> dict[str, Any]:
        return self.catalog.tool_providers(self.name)[provider]

    def resolve(self, name: str) -> str:
        return self.catalog.resolve_provider(self.name, name)

    def binary(self, env: dict[str, str]) -> str:
        binary = self.spec.get("binary") or self.name
        found = which(binary, env)
        if not found:
            raise AgentuseError(f"{self.name}: '{binary}' not found on PATH")
        return found

    # -- operations ---------------------------------------------------------

    def set(self, provider: str) -> str:
        """Persistently select a provider; return a one-line summary."""
        raise NotImplementedError

    def status(self) -> Status:
        raise NotImplementedError

    def launch_args(self, provider: str, env: dict[str, str]) -> list[str]:
        """Extra CLI arguments for a one-shot launch with `provider`."""
        return []

    def launch(
        self, provider: str | None, args: list[str], env: dict[str, str] | None = None
    ) -> Launch:
        """Build the argv/env to exec. provider=None keeps the configured one."""
        env = dict(os.environ if env is None else env)
        for key in self.spec.get("unset_env") or []:
            env.pop(key, None)

        if provider is None:
            current = self.status().provider
            if current:
                for key in self.provider_spec(current).get("unset_env") or []:
                    env.pop(key, None)
            # Export every key this tool can use, so switching models inside
            # the session (where the tool supports it) also works.
            for name, spec in self.catalog.tool_providers(self.name).items():
                self._export_keys(name, spec, env, required=False)
            self.prepare_default_env(current, env)
            return Launch([self.binary(env), *args], env)

        spec = self.provider_spec(provider)
        for key in spec.get("unset_env") or []:
            env.pop(key, None)
        self._export_keys(provider, spec, env, required=True)
        extra = self.launch_args(provider, env)
        return Launch([self.binary(env), *extra, *args], env)

    def prepare_default_env(self, current: str | None, env: dict[str, str]) -> None:
        """Hook for adapters whose default launch needs more than keys."""

    def _export_keys(
        self, provider: str, spec: dict[str, Any], env: dict[str, str], *, required: bool
    ) -> str | None:
        names = spec.get("key_env") or []
        credential = self.catalog.credential_for(self.name, provider)
        if not credential or not (names or required):
            return None
        if required:
            key = credentials.require(self.catalog, credential, env)
        else:
            key, _ = credentials.resolve(self.catalog, credential, env)
            if key is None:
                return None
        for name in names:
            env[name] = key
        return key

    def key(self, provider: str, env: dict[str, str]) -> str | None:
        credential = self.catalog.credential_for(self.name, provider)
        return credentials.require(self.catalog, credential, env) if credential else None

    def credential_command(self, provider: str) -> list[str] | None:
        credential = self.catalog.credential_for(self.name, provider)
        if not credential:
            return None
        return [*self_command(self.catalog), "key", credential]

    def match_status(self, field: str, value: Any, detail: str) -> Status:
        for name, spec in self.catalog.tool_providers(self.name).items():
            if spec.get(field) == value:
                return Status(name, detail)
        return Status(None, detail)


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------

CLAUDE_BASE_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS",
)


class Claude(Tool):
    name = "claude"

    def default_config(self) -> Path:
        base = os.environ.get("CLAUDE_CONFIG_DIR")
        return (expand(base) if base else expand("~/.claude")) / "settings.json"

    def managed_keys(self) -> set[str]:
        keys = set(CLAUDE_BASE_KEYS)
        for spec in self.catalog.tool_providers(self.name).values():
            keys.update((spec.get("env") or {}).keys())
        keys.add(self.spec.get("token_env") or "ANTHROPIC_AUTH_TOKEN")
        return keys

    def set(self, provider: str) -> str:
        path = self.config_path()
        settings = read_json(path)
        env = {k: v for k, v in (settings.get("env") or {}).items() if k not in self.managed_keys()}
        env.update({k: str(v) for k, v in (self.provider_spec(provider).get("env") or {}).items()})
        if env:
            settings["env"] = env
        else:
            settings.pop("env", None)

        # Surfaces that launch their own Claude binary (the VS Code extension,
        # desktop apps) never see the shell wrapper's token; apiKeyHelper
        # hands them the same key. Only the command is stored, never the key.
        command = self.credential_command(provider)
        helper = settings.get("apiKeyHelper")
        if command:
            settings["apiKeyHelper"] = shlex.join(command)
        elif isinstance(helper, str) and "agentuse" in helper:
            settings.pop("apiKeyHelper", None)
        write_json(path, settings)
        return f"claude: {provider} ({path})"

    def status(self) -> Status:
        env = read_json(self.config_path()).get("env") or {}
        base_url = env.get("ANTHROPIC_BASE_URL", "")
        model = env.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or env.get("ANTHROPIC_MODEL") or ""
        for name, spec in self.catalog.tool_providers(self.name).items():
            wanted = (spec.get("env") or {}).get("ANTHROPIC_BASE_URL", "")
            if wanted == base_url:
                return Status(name, model or "default models")
        return Status(None, f"base URL {base_url}")

    def launch(self, provider, args, env=None):
        env = dict(os.environ if env is None else env)
        # A stray exported override would silently beat settings.json.
        for key in self.managed_keys():
            env.pop(key, None)
        return super().launch(provider, args, env)

    def _token(self, provider: str, env: dict[str, str], *, required: bool) -> None:
        credential = self.catalog.credential_for(self.name, provider)
        if not credential:
            return
        if required:
            key = credentials.require(self.catalog, credential, env)
        else:
            key, _ = credentials.resolve(self.catalog, credential, env)
            if key is None:
                return
        env[self.spec.get("token_env") or "ANTHROPIC_AUTH_TOKEN"] = key

    def launch_args(self, provider, env):
        for key, value in (self.provider_spec(provider).get("env") or {}).items():
            env[key] = str(value)
        self._token(provider, env, required=True)
        return []

    def prepare_default_env(self, current, env):
        # settings.json already carries the base URL and models; add the token.
        if current:
            self._token(current, env, required=False)


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


class Codex(Tool):
    name = "codex"

    def default_config(self) -> Path:
        base = os.environ.get("CODEX_HOME")
        return (expand(base) if base else expand("~/.codex")) / "config.toml"

    def provider_table(self, provider: str) -> tuple[str, dict[str, Any] | None]:
        spec = self.provider_spec(provider)
        model_provider = spec.get("model_provider")
        if not isinstance(model_provider, str) or not isinstance(spec.get("model"), str):
            raise AgentuseError(f"codex: provider '{provider}' needs model and model_provider")
        table = spec.get("provider_table")
        if not table:
            return model_provider, None
        table = dict(table)
        command = self.credential_command(provider)
        if command and "auth" not in table and "env_key" not in table:
            table["auth"] = {"command": command[0], "args": command[1:]}
        return model_provider, table

    def set(self, provider: str) -> str:
        path = self.config_path()
        spec = self.provider_spec(provider)
        model_provider, table = self.provider_table(provider)
        lines = set_top_level(
            codex_lines(path), {"model": spec["model"], "model_provider": model_provider}
        )
        config = parse_toml(lines, path)
        if table and model_provider not in (config.get("model_providers") or {}):
            lines.append(toml_table(f"model_providers.{model_provider}", table))
        parse_toml(lines, path)
        atomic_write(path, "".join(lines))
        return f"codex: {provider} ({spec['model']} via {model_provider}, {path})"

    def status(self) -> Status:
        path = self.config_path()
        config = parse_toml(codex_lines(path), path)
        model_provider = config.get("model_provider", "openai")
        return self.match_status("model_provider", model_provider, config.get("model", "default model"))

    def launch_args(self, provider, env):
        # -c and -m are global flags: they must precede any subcommand.
        spec = self.provider_spec(provider)
        model_provider, table = self.provider_table(provider)
        args = ["-c", f"model_provider={model_provider}", "-m", spec["model"]]
        path = self.config_path()
        existing = parse_toml(codex_lines(path), path).get("model_providers") or {}
        if table and model_provider not in existing:
            args[:0] = ["-c", f"model_providers.{model_provider}={toml_value(table)}"]
        return args


# ---------------------------------------------------------------------------
# Kilo
# ---------------------------------------------------------------------------


class Kilo(Tool):
    name = "kilo"

    def default_config(self) -> Path:
        directory = _xdg("XDG_CONFIG_HOME", "~/.config") / "kilo"
        for name in ("kilo.jsonc", "kilo.json"):
            if (directory / name).exists():
                return directory / name
        return directory / "kilo.jsonc"

    def state_path(self) -> Path:
        configured = self.spec.get("state")
        if configured:
            return expand(configured)
        return _xdg("XDG_STATE_HOME", "~/.local/state") / "kilo" / "model.json"

    def models(self, provider: str) -> tuple[str, str]:
        spec = self.provider_spec(provider)
        model = spec.get("model")
        if not isinstance(model, str) or "/" not in model:
            raise AgentuseError(f"kilo: provider '{provider}' needs model = \"<provider>/<model>\"")
        return model, str(spec.get("small_model") or model)

    def set(self, provider: str) -> str:
        path = self.config_path()
        model, small_model = self.models(provider)
        note = ""
        if jsonc_has_comments(path):
            backup = path.with_name(path.name + ".bak")
            shutil.copy2(os.path.realpath(path), backup)
            note = f"; comments were dropped, original kept at {backup}"
        settings = read_json(path, jsonc=True)
        settings["model"] = model
        settings["small_model"] = small_model
        write_json(path, settings)

        # Kilo keeps the active model in its state file and prefers it over
        # the config, so both must move together.
        state_path = self.state_path()
        provider_id, _, model_id = model.partition("/")
        state = read_json(state_path)
        models = dict(state.get("model") or {})
        models["code"] = {"providerID": provider_id, "modelID": model_id}
        state["model"] = models
        recent = [
            item
            for item in (state.get("recent") or [])
            if not (
                isinstance(item, dict)
                and item.get("providerID") == provider_id
                and item.get("modelID") == model_id
            )
        ]
        state["recent"] = [{"providerID": provider_id, "modelID": model_id}, *recent[:9]]
        variants = dict(state.get("variant") or {})
        variants[model] = variants.get(model, "default")
        state["variant"] = variants
        write_json(state_path, state)
        return f"kilo: {provider} ({model}, {path}{note})"

    def status(self) -> Status:
        code = (read_json(self.state_path()).get("model") or {}).get("code") or {}
        if code.get("providerID") and code.get("modelID"):
            model = f"{code['providerID']}/{code['modelID']}"
        else:
            model = str(read_json(self.config_path(), jsonc=True).get("model", ""))
        if not model:
            return Status(None, "no model set")
        providers = self.catalog.tool_providers(self.name)
        for name, spec in providers.items():
            if spec.get("model") == model:
                return Status(name, model)
        prefix = model.partition("/")[0]
        for name, spec in providers.items():
            if str(spec.get("model", "")).partition("/")[0] == prefix:
                return Status(name, model)
        return Status(None, model)

    def launch_args(self, provider, env):
        return ["-m", self.models(provider)[0]]


# ---------------------------------------------------------------------------
# Pi
# ---------------------------------------------------------------------------


class Pi(Tool):
    name = "pi"

    def default_config(self) -> Path:
        base = os.environ.get("PI_CODING_AGENT_DIR")
        return (expand(base) if base else expand("~/.pi/agent")) / "settings.json"

    def ids(self, provider: str) -> tuple[str, str]:
        spec = self.provider_spec(provider)
        target, model = spec.get("provider"), spec.get("model")
        if not isinstance(target, str) or not isinstance(model, str):
            raise AgentuseError(f"pi: provider '{provider}' needs provider and model")
        return target, model

    def set(self, provider: str) -> str:
        path = self.config_path()
        target, model = self.ids(provider)
        settings = read_json(path)
        settings["defaultProvider"] = target
        settings["defaultModel"] = model
        settings["enabledModels"] = [f"{target}/{model}"]
        write_json(path, settings)
        return f"pi: {provider} ({target}/{model}, {path})"

    def status(self) -> Status:
        settings = read_json(self.config_path())
        target = settings.get("defaultProvider")
        return self.match_status("provider", target, f"{target}/{settings.get('defaultModel')}")

    def launch_args(self, provider, env):
        target, model = self.ids(provider)
        # --models is required: --api-key needs an explicit model scope.
        args = ["--provider", target, "--models", f"{target}/{model}", "--model", model]
        if self.provider_spec(provider).get("api_key_flag"):
            key = self.key(provider, env)
            if key:
                args += ["--api-key", key]
        return args


# ---------------------------------------------------------------------------
# Hermes
# ---------------------------------------------------------------------------


class Hermes(Tool):
    name = "hermes"

    def default_config(self) -> Path:
        base = os.environ.get("HERMES_HOME")
        return (expand(base) if base else expand("~/.hermes")) / "config.yaml"

    def ids(self, provider: str) -> tuple[str, str]:
        spec = self.provider_spec(provider)
        target, model = spec.get("provider"), spec.get("model")
        if not isinstance(target, str) or not isinstance(model, str):
            raise AgentuseError(f"hermes: provider '{provider}' needs provider and model")
        return target, model

    def _hermes(self, *args: str) -> str:
        binary = self.binary(dict(os.environ))
        result = subprocess.run([binary, *args], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise AgentuseError(f"hermes {' '.join(args)} failed: {message}")
        return result.stdout.strip()

    def set(self, provider: str) -> str:
        # Hermes' own writer keeps plugins, skills and unrelated settings.
        target, model = self.ids(provider)
        self._hermes("config", "set", "model.provider", target)
        self._hermes("config", "set", "model.default", model)
        return f"hermes: {provider} ({target}/{model})"

    def status(self) -> Status:
        target = self._hermes("config", "get", "model.provider")
        model = self._hermes("config", "get", "model.default")
        return self.match_status("provider", target, f"{target}/{model}")

    def launch_args(self, provider, env):
        target, model = self.ids(provider)
        return ["--provider", target, "-m", model]


ADAPTERS: dict[str, type[Tool]] = {
    cls.name: cls for cls in (Claude, Codex, Kilo, Pi, Hermes)
}

TOOL_ALIASES = {
    "cc": "claude",
    "claude-code": "claude",
    "cx": "codex",
    "k": "kilo",
    "kilocode": "kilo",
    "h": "hermes",
}


def get(catalog: Catalog, name: str) -> Tool:
    name = TOOL_ALIASES.get(name, name)
    adapter = ADAPTERS.get(name)
    if adapter is None:
        known = ", ".join(sorted(ADAPTERS))
        raise AgentuseError(f"unknown tool '{name}' (supported: {known})")
    return adapter(catalog)


def configured(catalog: Catalog) -> list[str]:
    return [name for name in ADAPTERS if name in catalog.tools]
