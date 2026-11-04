"""Generate the short commands: ccuse, cxuse, claude-go, codex-or, ..."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from agentuse import AgentuseError
from agentuse.catalog import Catalog
from agentuse.tools import ADAPTERS, SHIM_MARKER, is_shim, self_command

DEFAULT_SWITCH = {
    "claude": "ccuse",
    "codex": "cxuse",
    "kilo": "kuse",
    "pi": "piuse",
    "hermes": "huse",
}


@dataclass
class Shim:
    name: str
    args: list[str]  # arguments after the agentuse command
    passthrough_sep: bool = False  # insert `--` before "$@"

    def render(self, command: list[str]) -> str:
        call = shlex.join([*command, *self.args])
        tail = ' -- "$@"' if self.passthrough_sep else ' "$@"'
        return f"#!/bin/sh\n{SHIM_MARKER}\nexec {call}{tail}\n"


def plan(catalog: Catalog, tools: list[str] | None = None, *, wrap: bool = False) -> list[Shim]:
    shims: list[Shim] = []
    for tool, spec in catalog.tools.items():
        if tool not in ADAPTERS or (tools and tool not in tools):
            continue
        switch = spec.get("switch_command", DEFAULT_SWITCH.get(tool))
        if switch:
            shims.append(Shim(switch, ["use", tool]))
        prefix = spec.get("command") or spec.get("binary") or tool
        prefix = os.path.basename(prefix)
        for provider in catalog.tool_providers(tool):
            names = catalog.providers.get(provider, {}).get("shim_names") or [provider]
            for name in names:
                shims.append(Shim(f"{prefix}-{name}", ["run", tool, provider], True))
        if wrap:
            shims.append(Shim(prefix, ["run", tool, "default"], True))
    return shims


def install(
    catalog: Catalog,
    directory: Path,
    tools: list[str] | None = None,
    *,
    wrap: bool = False,
    force: bool = False,
    command: list[str] | None = None,
) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    command = command or self_command(catalog)
    written: list[Path] = []
    for shim in plan(catalog, tools, wrap=wrap):
        path = directory / shim.name
        if path.exists() and not is_shim(path) and not force:
            raise AgentuseError(
                f"{path} exists and was not written by agentuse (use --force to replace it)"
            )
        path.write_text(shim.render(command), encoding="utf-8")
        path.chmod(0o755)
        written.append(path)
    return written


def uninstall(directory: Path) -> list[Path]:
    removed: list[Path] = []
    if not directory.is_dir():
        return removed
    for path in sorted(directory.iterdir()):
        if path.is_file() and not path.is_symlink() and is_shim(path):
            path.unlink()
            removed.append(path)
    return removed
