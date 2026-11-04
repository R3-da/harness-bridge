"""agentuse command line."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from agentuse import AgentuseError, __version__, credentials, shims, tools
from agentuse.catalog import Catalog, user_catalog_path
from agentuse.files import expand

USAGE_EXAMPLES = """\
examples:
  agentuse status                    every harness and its provider
  agentuse use codex go              Codex on OpenCode Go from now on
  agentuse use claude sub            Claude Code back on the subscription
  agentuse run kilo openrouter       one OpenRouter session, config untouched
  agentuse run codex go -- exec "fix the tests"
  agentuse install-shims             ccuse, cxuse, claude-go, codex-or, ...
"""

STARTER_CATALOG = """\
# agentuse catalog: merged on top of the built-in defaults.
# See every default with `agentuse catalog`. Only list what you change.

# Example: read the OpenCode Go key from 1Password instead.
# [credentials.opencode-go]
# sources = [{ command = ["op", "read", "op://Private/OpenCode Go/credential"] }]

# Example: use a different model for Codex on OpenCode Go.
# [tools.codex.providers.go]
# model = "glm-5.3"

# Example: if your configs are synced across machines, store "agentuse"
# instead of an absolute path in Codex auth commands and apiKeyHelper.
# [settings]
# self = "agentuse"
"""


def _catalog(args: argparse.Namespace) -> Catalog:
    return Catalog.load(expand(args.catalog) if args.catalog else None)


def cmd_status(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    names = args.tools or tools.configured(catalog)
    width = max((len(name) for name in names), default=0)
    for name in names:
        tool = tools.get(catalog, name)
        installed = tools.which(tool.spec.get("binary") or tool.name, dict(os.environ))
        try:
            status = tool.status()
            provider = status.provider or "unrecognised"
            line = f"{tool.name:<{width}}  {provider:<12} {status.detail}"
        except AgentuseError as error:
            line = f"{tool.name:<{width}}  {'error':<12} {error}"
        if not installed:
            line += "  [not installed]"
        print(line)
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    tool = tools.get(catalog, args.tool)
    if not args.provider or args.provider == "status":
        return cmd_status(argparse.Namespace(**{**vars(args), "tools": [tool.name]}))
    provider = tool.resolve(args.provider)
    print(tool.set(provider))
    return 0


def _split_run(rest: list[str]) -> tuple[str | None, list[str]]:
    if not rest:
        return None, []
    head, tail = rest[0], rest[1:]
    if head == "--":
        return None, tail
    if tail[:1] == ["--"]:
        tail = tail[1:]
    return head, tail


def cmd_run(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    tool = tools.get(catalog, args.tool)
    provider_name, passthrough = _split_run(args.rest)
    provider: str | None
    if provider_name in (None, "default", "-"):
        provider = None
    else:
        try:
            provider = tool.resolve(provider_name)
        except AgentuseError:
            # Not a provider name: it belongs to the tool.
            provider, passthrough = None, [provider_name, *passthrough]
    launch = tool.launch(provider, passthrough)
    if args.print:
        print(json.dumps({"argv": launch.argv}, indent=2))
        return 0
    os.execve(launch.argv[0], launch.argv, launch.env)
    return 127  # pragma: no cover


def cmd_key(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    sys.stdout.write(credentials.require(catalog, args.credential) + "\n")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    names = [tools.TOOL_ALIASES.get(t, t) for t in args.tools] or tools.configured(catalog)
    for name in names:
        tool = tools.get(catalog, name)
        print(f"{tool.name}:")
        for provider, spec in catalog.tool_providers(tool.name).items():
            meta = catalog.providers.get(provider, {})
            model = spec.get("model") or (spec.get("env") or {}).get(
                "ANTHROPIC_DEFAULT_SONNET_MODEL", "tool default"
            )
            aliases = ", ".join(meta.get("aliases") or [])
            sub = " (subscription)" if tool.spec.get("subscription") == provider else ""
            print(f"  {provider:<12} {model}{sub}" + (f"  aliases: {aliases}" if aliases else ""))
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    if args.path:
        print(user_catalog_path())
        return 0
    print(json.dumps(catalog.data, indent=2))
    print(f"# sources: {', '.join(catalog.sources)}", file=sys.stderr)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = expand(args.catalog) if args.catalog else user_catalog_path()
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite)")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STARTER_CATALOG, encoding="utf-8")
    print(f"wrote {path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    problems = 0
    print(f"catalog: {', '.join(catalog.sources)}")
    print(f"agentuse command in configs: {' '.join(tools.self_command(catalog))}")
    print("credentials:")
    for name in catalog.credentials:
        key, tried = credentials.resolve(catalog, name)
        if key:
            print(f"  ok       {name} (from {tried[-1]})")
        else:
            print(f"  missing  {name} (tried: {'; '.join(tried)})")
    print("tools:")
    for name in tools.configured(catalog):
        tool = tools.get(catalog, name)
        binary = tools.which(tool.spec.get("binary") or tool.name, dict(os.environ))
        if not binary:
            print(f"  -        {name}: not installed")
            continue
        try:
            status = tool.status()
            print(f"  ok       {name}: {status.provider or 'unrecognised'} ({status.detail})")
            print(f"           binary {binary}, config {tool.config_path()}")
            if status.provider:
                credential = catalog.credential_for(name, status.provider)
                if credential and not credentials.resolve(catalog, credential)[0]:
                    print(f"  problem  {name} uses {status.provider} but '{credential}' has no key")
                    problems += 1
        except AgentuseError as error:
            print(f"  problem  {name}: {error}")
            problems += 1
    return 1 if problems else 0


def cmd_install_shims(args: argparse.Namespace) -> int:
    catalog = _catalog(args)
    directory = expand(args.dir)
    wanted = [tools.TOOL_ALIASES.get(t, t) for t in args.tools] or None
    command = shlex.split(args.command) if args.command else None
    written = shims.install(
        catalog, directory, wanted, wrap=args.wrap, force=args.force, command=command
    )
    print(f"installed {len(written)} commands in {directory}:")
    print("  " + " ".join(path.name for path in written))
    on_path = str(directory) in (os.environ.get("PATH") or "").split(os.pathsep)
    if not on_path:
        print(f"note: {directory} is not on PATH")
    return 0


def cmd_uninstall_shims(args: argparse.Namespace) -> int:
    removed = shims.uninstall(expand(args.dir))
    print(f"removed {len(removed)} agentuse commands from {expand(args.dir)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentuse",
        description="Switch coding-agent harnesses between subscriptions and API providers.",
        epilog=USAGE_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"agentuse {__version__}")
    parser.add_argument("--catalog", help="catalog file (default: $AGENTUSE_CATALOG or ~/.config/agentuse/catalog.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="show each harness's provider")
    p.add_argument("tools", nargs="*")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("use", help="persistently switch a harness's provider")
    p.add_argument("tool")
    p.add_argument("provider", nargs="?", help="omit (or 'status') to print the current one")
    p.set_defaults(func=cmd_use)

    p = sub.add_parser("run", help="launch a harness, optionally on another provider for this run only")
    p.add_argument("tool")
    p.add_argument("rest", nargs=argparse.REMAINDER, help="[provider|default] [--] tool arguments")
    p.add_argument("--print", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("key", help="print a credential (used by Codex auth commands and apiKeyHelper)")
    p.add_argument("credential")
    p.set_defaults(func=cmd_key)

    p = sub.add_parser("providers", help="list the providers and models each harness can use")
    p.add_argument("tools", nargs="*")
    p.set_defaults(func=cmd_providers)

    p = sub.add_parser("catalog", help="print the merged catalog as JSON")
    p.add_argument("--path", action="store_true", help="print the user catalog path instead")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("init", help="write a starter user catalog")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor", help="check binaries, configs and credentials")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("install-shims", help="create ccuse, cxuse, claude-go, codex-or, ...")
    p.add_argument("tools", nargs="*", help="limit to these harnesses")
    p.add_argument("--dir", default="~/.local/bin")
    p.add_argument("--wrap", action="store_true", help="also wrap the harness itself (claude, codex, ...) so plain launches get keys injected")
    p.add_argument("--force", action="store_true", help="replace files agentuse did not write")
    p.add_argument("--command", help="how shims invoke agentuse (default: this agentuse's path)")
    p.set_defaults(func=cmd_install_shims)

    p = sub.add_parser("uninstall-shims", help="remove commands created by install-shims")
    p.add_argument("--dir", default="~/.local/bin")
    p.set_defaults(func=cmd_uninstall_shims)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AgentuseError as error:
        print(f"agentuse: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130
