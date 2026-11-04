# harness-bridge

One catalog and one command, `hbridge`, to point your coding-agent harnesses at the
provider you want: their own subscription, an **OpenCode Go** subscription,
or **OpenRouter**.

```console
$ hbridge status
claude  anthropic    default models
codex   go           deepseek-v4.1-flash
kilo    go           opencode-go/deepseek-v4.1-flash
pi      openai       openai-codex/gpt-5.4
hermes  openrouter   openrouter/deepseek/deepseek-v4.1-flash

$ cxuse go            # Codex on OpenCode Go from now on (desktop app included)
$ ccuse sub           # Claude Code back on the Claude subscription
$ kilo-or             # one Kilo session on OpenRouter; config untouched
```

Supported harnesses: **Claude Code**, **Codex** (CLI, TUI and the ChatGPT
desktop app), **Kilo**, **Pi** and **Hermes**. No dependencies beyond
Python 3.11+.

## Why

An OpenCode Go subscription works with many harnesses, but each one wants
its provider configured differently: an `env` block in Claude Code's
`settings.json`, `model_provider` plus a `[model_providers.*]` table in
Codex's `config.toml`, a model plus a separate state file in Kilo, and so on.
Each also has its own traps (see [Harness notes](#harness-notes)).
hbridge handles all of that from one catalog.

## Install

```sh
uv tool install git+https://github.com/R3-da/harness-bridge   # or: pipx install git+...
hbridge install-shims        # optional: ccuse, cxuse, claude-go, codex-or, ...
hbridge doctor               # check binaries, configs and keys
```

Nix users: see [Nix and home-manager](#nix-and-home-manager).

## Two kinds of switch

| | Command | Writes config? | Reaches |
| --- | --- | --- | --- |
| **Permanent** | `hbridge use <tool> <provider>` (or `ccuse go`, …) | yes | every surface that reads the tool's config: shells, IDE extensions, desktop apps |
| **One-shot** | `hbridge run <tool> <provider> -- args` (or `codex-go`, …) | never | only the process it starts |

A permanent switch is the only way to reach surfaces that bypass your shell.
The ChatGPT desktop app, for example, runs its own bundled Codex that reads
`~/.codex/config.toml` directly. A one-shot never changes your default.

## Commands

```text
hbridge status [tool...]          current provider and model of each harness
hbridge use <tool> [provider]     permanent switch (no provider: show status)
hbridge run <tool> [provider] [-- args]
                                   launch; with a provider, only for this run
hbridge providers [tool...]       what each harness can use
hbridge key <credential>          print a key (used by config-file helpers)
hbridge doctor                    check binaries, configs and credentials
hbridge catalog [--path]          the merged catalog as JSON
hbridge init                      write a starter ~/.config/hbridge/catalog.toml
hbridge install-shims [--dir D] [--wrap] [tool...]
hbridge uninstall-shims [--dir D]
```

Tools: `claude` (`cc`), `codex` (`cx`), `kilo` (`k`), `pi`, `hermes` (`h`).
Providers: `anthropic`, `openai`, `go` (`opencode-go`), `openrouter` (`or`).
`sub` / `subscription` always means the tool's own subscription.

### Shims

`hbridge install-shims` writes short commands into `~/.local/bin`:

| Shim | Runs |
| --- | --- |
| `ccuse`, `cxuse`, `kuse`, `piuse`, `huse` | `hbridge use <tool> "$@"` |
| `<tool>-<provider>`, e.g. `claude-go`, `codex-or`, `kilo-openai` | `hbridge run <tool> <provider> -- "$@"` |
| with `--wrap`: `claude`, `codex`, … | `hbridge run <tool> default -- "$@"` |

The `--wrap` shims put the configured provider's key into plain launches.
That matters for Claude Code on OpenCode Go when you don't rely on
`apiKeyHelper`. When hbridge looks up the real binary, it skips its own
shims, so shadowing `claude` on `PATH` is safe. `uninstall-shims` only
removes files that hbridge wrote.

## The catalog

Built-in defaults ship with hbridge: providers, credentials, and a model
per harness and provider. Your file at `~/.config/hbridge/catalog.toml` (or
`$HBRIDGE_CATALOG`) is deep-merged on top, so it only needs what you change:

```toml
# A different model for Codex on OpenCode Go.
[tools.codex.providers.go]
model = "glm-5.3"

# Claude Code on Go: Sonnet-tier work on a bigger model.
[tools.claude.providers.go.env]
ANTHROPIC_DEFAULT_SONNET_MODEL = "kimi-k3"
```

Run `hbridge catalog` to see the merged result, and
[`default_catalog.toml`](src/hbridge/default_catalog.toml) for every key,
with comments.

### Credentials

Keys are read from the sources you list, first match wins. They are never
written into a config file:

```toml
[credentials.opencode-go]
sources = [
  { env = "OPENCODE_GO_API_KEY" },
  { file = "~/.secrets/opencode-go" },
  { command = ["op", "read", "op://Private/OpenCode Go/credential"] },
  { opencode_auth = "opencode-go" },   # what `opencode auth login` stores
]
```

Some surfaces can't receive environment variables, such as Codex in the
desktop app or Claude Code in VS Code. For those, the permanent switch writes
a command that calls `hbridge key <credential>` at request time: Codex's
`[model_providers.<id>.auth]` and Claude Code's `apiKeyHelper`. By default
it stores the absolute path of the hbridge that ran the switch. If you sync
those config files across machines, set `[settings] self = "hbridge"` so
they store the bare command name instead.

## Harness notes

What each permanent switch edits, and the traps it handles:

- **Claude Code**. Edits `settings.json` (`$CLAUDE_CONFIG_DIR`, default
  `~/.claude`): sets the `env` block (base URL and model tiers) and
  `apiKeyHelper`, so the VS Code extension and other bundled binaries get the
  key too. Your other `env` keys and `model` are left alone. Switching back to
  `anthropic` removes them, and only removes an `apiKeyHelper` that hbridge
  wrote. Launches clear stray `ANTHROPIC_*` variables, which would otherwise
  override the configuration. Non-Claude models get
  `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`.
- **Codex**. Edits `config.toml` (`$CODEX_HOME`, default `~/.codex`): sets
  the top-level `model` and `model_provider` with line edits, so comments and
  layout survive, and adds the `[model_providers.<id>]` table if it is
  missing. A table you already have is never touched. Launches unset
  `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `CODEX_API_KEY`, because an inherited
  key beats the ChatGPT login and would silently take you off the
  subscription. One-shots pass `-c`/`-m` before any subcommand; Codex
  requires that order. The desktop app sometimes writes a second top-level
  `model` pair; hbridge removes it.
- **Kilo**. Edits `kilo.jsonc` (or `kilo.json`) under `$XDG_CONFIG_HOME/kilo`
  (`model`, `small_model`) and the active model in
  `$XDG_STATE_HOME/kilo/model.json`, which Kilo prefers over the config. A
  file with comments is backed up to `kilo.jsonc.bak` before being rewritten
  as plain JSON.
- **Pi**. Edits `~/.pi/agent/settings.json` (`$PI_CODING_AGENT_DIR`):
  `defaultProvider`, `defaultModel` and an exact `enabledModels` scope.
  One-shots pass `--provider --models --model`, plus `--api-key`, which
  beats a stale entry in Pi's `auth.json`.
- **Hermes**. Calls `hermes config set model.provider/model.default`, so
  plugins and unrelated settings are preserved. OpenCode Go requires Hermes
  0.21.5 or newer, the first release that sends the `x-opencode-session`
  header.

Writes go through symlinks, so files managed by home-manager, stow or chezmoi
stay linked to your dotfiles repository. Every write is atomic and keeps the
file's permissions.

## Nix and home-manager

```nix
{
  inputs.hbridge.url = "github:R3-da/harness-bridge";

  # in your home-manager configuration:
  imports = [ inputs.hbridge.homeManagerModules.default ];
  programs.hbridge = {
    enable = true;
    shims.wrap = true;               # claude/codex/... inject keys on launch
    harnesses = {                    # installed, and launched by store path
      claude = pkgs.claude-code;
      codex = pkgs.codex;
    };
    # Machine-specific values, generated into ~/.config/hbridge/catalog.toml:
    settings.credentials.opencode-go.sources = [
      { file = config.sops.secrets.opencode_go_api_key.path; }
    ];
    # Models you want to edit without a rebuild, in your dotfiles:
    catalogFile = "${config.home.homeDirectory}/dotfiles/hbridge.toml";
  };
}
```

With `shims.wrap`, the wrappers take over the profile's `claude`, `codex`,
… entries, so list the harnesses in `harnesses`: hbridge then launches them
by store path, and the rest of each package stays on PATH.

The module installs the package, writes `~/.config/hbridge/catalog.toml`
(with `catalogFile` as an `include`), and builds the shims from the built-in
catalog plus `settings`. It sets `settings.self` to the profile's
`bin/hbridge`, so commands written into config files survive upgrades and
garbage collection. Providers that exist only in `catalogFile` get no
one-shot shims; run `hbridge install-shims` for those.

A catalog can `include` other catalogs. They are merged before the
including file's own keys: `include = ["~/dotfiles/hbridge.toml"]`.
`nix build` runs the test suite.

## Development

```sh
uv run --with pytest python -m pytest      # or: nix flake check
```

The tests use fake harness binaries and a temporary `HOME`; they never touch
your real configuration.

## License

MIT
