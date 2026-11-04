"""Load the provider catalog: built-in defaults with the user's file on top."""

from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from agentuse import AgentuseError
from agentuse.files import expand

SUBSCRIPTION_ALIASES = {"sub", "subscription"}


def default_catalog_text() -> str:
    return resources.files("agentuse").joinpath("default_catalog.toml").read_text("utf-8")


def user_catalog_path() -> Path:
    explicit = os.environ.get("AGENTUSE_CATALOG")
    if explicit:
        return expand(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return expand(base) / "agentuse" / "catalog.toml"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge tables recursively; any non-table value in overlay replaces."""
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _load_file(
    path: Path, data: dict[str, Any], sources: list[str], missing: list[str], seen: set[Path]
) -> dict[str, Any]:
    """Merge `path` into `data`: its includes first, then its own keys."""
    resolved = path.resolve()
    if resolved in seen:
        raise AgentuseError(f"catalog include cycle at {path}")
    seen.add(resolved)
    try:
        overlay = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise AgentuseError(f"invalid TOML in {path}: {error}") from error
    includes = overlay.pop("include", [])
    if isinstance(includes, str):
        includes = [includes]
    for include in includes:
        target = expand(include)
        if not target.is_absolute():
            target = path.parent / target
        if target.exists():
            data = _load_file(target, data, sources, missing, seen)
        else:
            missing.append(str(target))
    sources.append(str(path))
    return deep_merge(data, overlay)


@dataclass
class Catalog:
    data: dict[str, Any]
    sources: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "Catalog":
        """Built-in defaults, then the user catalog (and anything it includes)."""
        data = tomllib.loads(default_catalog_text())
        sources, missing = ["built-in"], []
        path = path or user_catalog_path()
        if path.exists():
            data = _load_file(path, data, sources, missing, set())
        return cls(data, sources, missing)

    # -- sections ---------------------------------------------------------

    @property
    def settings(self) -> dict[str, Any]:
        return self.data.get("settings") or {}

    @property
    def providers(self) -> dict[str, dict[str, Any]]:
        return self.data.get("providers") or {}

    @property
    def credentials(self) -> dict[str, dict[str, Any]]:
        return self.data.get("credentials") or {}

    @property
    def tools(self) -> dict[str, dict[str, Any]]:
        return self.data.get("tools") or {}

    def tool(self, name: str) -> dict[str, Any]:
        tools = self.tools
        if name not in tools:
            known = ", ".join(sorted(tools)) or "none"
            raise AgentuseError(f"unknown tool '{name}' (known: {known})")
        return tools[name]

    def tool_providers(self, tool: str) -> dict[str, dict[str, Any]]:
        return self.tool(tool).get("providers") or {}

    # -- name resolution --------------------------------------------------

    def resolve_provider(self, tool: str, name: str) -> str:
        """Map a typed provider name or alias to the tool's provider key."""
        available = self.tool_providers(tool)
        if name in SUBSCRIPTION_ALIASES:
            name = self.tool(tool).get("subscription") or name
        if name in available:
            return name
        for provider, spec in self.providers.items():
            if name in (spec.get("aliases") or []) and provider in available:
                return provider
        known = ", ".join(sorted(available)) or "none"
        raise AgentuseError(f"{tool}: unknown provider '{name}' (expected one of: {known})")

    def provider_names(self, tool: str) -> list[str]:
        """Every name that resolves for this tool, for shims and completion."""
        names: list[str] = []
        for provider in self.tool_providers(tool):
            names.append(provider)
            names.extend(self.providers.get(provider, {}).get("aliases") or [])
        return names

    def credential_for(self, tool: str, provider: str) -> str | None:
        spec = self.tool_providers(tool).get(provider) or {}
        if "credential" in spec:
            return spec["credential"] or None
        return self.providers.get(provider, {}).get("credential")
