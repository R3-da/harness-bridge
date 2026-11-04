"""Resolve API keys from the sources a catalog lists."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from agentuse import AgentuseError
from agentuse.catalog import Catalog
from agentuse.files import expand

OPENCODE_AUTH = "~/.local/share/opencode/auth.json"


def describe(source: dict[str, Any]) -> str:
    if "env" in source:
        return f"env {source['env']}"
    if "file" in source:
        return f"file {source['file']}"
    if "command" in source:
        command = source["command"]
        return "command " + (" ".join(command) if isinstance(command, list) else str(command))
    if "opencode_auth" in source:
        return f"opencode auth.json entry '{source['opencode_auth']}'"
    return f"unknown source {source!r}"


def _from_source(source: dict[str, Any], env: dict[str, str]) -> str | None:
    if "env" in source:
        return env.get(source["env"]) or None
    if "file" in source:
        path = expand(source["file"])
        if path.is_file() and os.access(path, os.R_OK):
            return path.read_text(encoding="utf-8").strip() or None
        return None
    if "command" in source:
        command = source["command"]
        if isinstance(command, str):
            command = ["/bin/sh", "-c", command]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    if "opencode_auth" in source:
        path = expand(source.get("path") or env.get("OPENCODE_AUTH_FILE") or OPENCODE_AUTH)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8")).get(source["opencode_auth"])
        except (json.JSONDecodeError, AttributeError):
            return None
        if isinstance(entry, dict):
            value = entry.get(source.get("field", "key"))
            return value if isinstance(value, str) and value else None
        return None
    raise AgentuseError(f"unknown credential source {source!r}")


def resolve(
    catalog: Catalog, name: str, env: dict[str, str] | None = None
) -> tuple[str | None, list[str]]:
    """Return (key, sources tried). The key is None when nothing matched."""
    env = dict(os.environ) if env is None else env
    spec = catalog.credentials.get(name)
    if spec is None:
        raise AgentuseError(f"unknown credential '{name}'")
    tried: list[str] = []
    for source in spec.get("sources") or []:
        tried.append(describe(source))
        value = _from_source(source, env)
        if value:
            return value, tried
    return None, tried


def require(catalog: Catalog, name: str, env: dict[str, str] | None = None) -> str:
    key, tried = resolve(catalog, name, env)
    if key is None:
        where = "; ".join(tried) or "no sources configured"
        raise AgentuseError(f"no key found for credential '{name}' (tried: {where})")
    return key
