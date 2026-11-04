"""Config file reading and writing that keeps users' files intact.

Two rules apply everywhere:

* Writes go through symlinks. Dotfile managers (Nix home-manager, stow,
  chezmoi) often symlink these files into a repository; replacing the link
  itself would silently detach the file from that repository.
* Writes are atomic and keep the file's permissions.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from agentuse import AgentuseError


def expand(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path))))


def atomic_write(path: Path, text: str) -> None:
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# --------------------------------------------------------------------------
# JSON / JSONC
# --------------------------------------------------------------------------

def strip_jsonc(text: str) -> tuple[str, bool]:
    """Remove // and /* */ comments and trailing commas outside strings.

    Returns the plain JSON text and whether anything was removed.
    """
    out: list[str] = []
    i, n = 0, len(text)
    changed = False
    in_string = False
    while i < n:
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
            changed = True
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            changed = True
        else:
            out.append(char)
            i += 1
    plain = "".join(out)
    without_commas = re.sub(r",(\s*[}\]])", r"\1", plain)
    return without_commas, changed or without_commas != plain


def read_json(path: Path, *, jsonc: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    if jsonc:
        text, _ = strip_jsonc(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise AgentuseError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise AgentuseError(f"expected a JSON object in {path}")
    return value


def jsonc_has_comments(path: Path) -> bool:
    if not path.exists():
        return False
    _, changed = strip_jsonc(path.read_text(encoding="utf-8"))
    return changed


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# TOML (Codex config.toml)
#
# There is no TOML writer in the standard library, and a round trip through
# one would drop the user's comments anyway. Codex edits are therefore line
# edits: replace or insert the top-level `model` / `model_provider` keys, and
# append whole tables that are missing.
# --------------------------------------------------------------------------

_SECTION = re.compile(r"^\s*\[")
_TOP_KEY = re.compile(r"^\s*(model|model_provider)\s*=")


def _outside_strings(lines: list[str]) -> list[bool]:
    """For each line, whether it starts outside a multi-line string."""
    result: list[bool] = []
    delimiter: str | None = None
    for line in lines:
        result.append(delimiter is None)
        position = 0
        while True:
            if delimiter is None:
                found = [(line.find(d, position), d) for d in ('"""', "'''")]
                found = [(i, d) for i, d in found if i != -1]
                hash_at = line.find("#", position)
                if not found:
                    break
                index, quote = min(found)
                if hash_at != -1 and hash_at < index:
                    break  # the rest of the line is a comment
                delimiter, position = quote, index + 3
            else:
                index = line.find(delimiter, position)
                while index > 0 and delimiter == '"""' and line[index - 1] == "\\":
                    index = line.find(delimiter, index + 1)
                if index == -1:
                    break
                delimiter, position = None, index + 3
    return result


def _first_section(lines: list[str]) -> int:
    outside = _outside_strings(lines)
    return next(
        (i for i, line in enumerate(lines) if outside[i] and _SECTION.match(line)), len(lines)
    )


def codex_lines(path: Path) -> list[str]:
    """Read config.toml, dropping duplicate top-level model keys.

    Some writers (notably the Codex desktop app) append a second top-level
    model/model_provider pair, which makes the TOML invalid. Keep the first
    pair; a later write then repairs the file.
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    first = _first_section(lines)
    outside = _outside_strings(lines)
    seen: set[str] = set()
    kept: list[str] = []
    for index, line in enumerate(lines):
        match = _TOP_KEY.match(line) if outside[index] else None
        if match and index < first:
            if match.group(1) in seen:
                continue
            seen.add(match.group(1))
        kept.append(line)
    return kept


def parse_toml(lines: list[str], path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads("".join(lines))
    except tomllib.TOMLDecodeError as error:
        raise AgentuseError(f"invalid TOML in {path}: {error}") from error


def set_top_level(lines: list[str], values: dict[str, str]) -> list[str]:
    lines = list(lines)
    first = _first_section(lines)
    outside = _outside_strings(lines)
    seen: set[str] = set()
    for index in range(first):
        match = _TOP_KEY.match(lines[index]) if outside[index] else None
        if match and match.group(1) in values:
            key = match.group(1)
            lines[index] = f"{key} = {toml_value(values[key])}\n"
            seen.add(key)
    missing = [key for key in values if key not in seen]
    if missing:
        block = "".join(f"{key} = {toml_value(values[key])}\n" for key in missing)
        lines.insert(first, block)
    return lines


def toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{toml_key(k)} = {toml_value(v)}" for k, v in value.items())
        return "{ " + inner + " }" if inner else "{}"
    raise AgentuseError(f"cannot write {type(value).__name__} to TOML")


def toml_table(header: str, table: dict[str, Any]) -> str:
    """Render a table; nested dicts become sub-tables."""
    scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
    nested = {k: v for k, v in table.items() if isinstance(v, dict)}
    text = f"\n[{header}]\n"
    text += "".join(f"{toml_key(k)} = {toml_value(v)}\n" for k, v in scalars.items())
    for key, sub in nested.items():
        text += toml_table(f"{header}.{toml_key(key)}", sub)
    return text
