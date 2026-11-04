# agentuse

One catalog and one command to point your coding-agent harnesses at the
provider you want: their own subscription, an **OpenCode Go** subscription,
or **OpenRouter**.

```console
$ agentuse status
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
agentuse handles all of that from one catalog.

## Install

```sh
uv tool install git+https://github.com/R3-da/agentuse   # or: pipx install git+...
agentuse install-shims        # optional: ccuse, cxuse, claude-go, codex-or, ...
agentuse doctor               # check binaries, configs and keys
```

Nix users: see [Nix and home-manager](#nix-and-home-manager).

## Two kinds of switch

| | Command | Writes config? | Reaches |
| --- | --- | --- | --- |
| **Permanent** | `agentuse use <tool> <provider>` (or `ccuse go`, …) | yes | every surface that reads the tool's config: shells, IDE extensions, desktop apps |
| **One-shot** | `agentuse run <tool> <provider> -- args` (or `codex-go`, …) | never | only the process it starts |

A permanent switch is the only way to reach surfaces that bypass your shell.
The ChatGPT desktop app, for example, runs its own bundled Codex that reads
`~/.codex/config.toml` directly. A one-shot never changes your default.

## Commands

```text
agentuse status [tool...]          current provider and model of each harness
agentuse use <tool> [provider]     permanent switch (no provider: show status)
agentuse run <tool> [provider] [-- args]
                                   launch; with a provider, only for this run
agentuse providers [tool...]       what each harness can use
agentuse key <credential>          print a key (used by config-file helpers)
agentuse doctor                    check binaries, configs and credentials
agentuse catalog [--path]          the merged catalog as JSON
agentuse init                      write a starter ~/.config/agentuse/catalog.toml
agentuse install-shims [--dir D] [--wrap] [tool...]
agentuse uninstall-shims [--dir D]
```

Tools: `claude` (`cc`), `codex` (`cx`), `kilo` (`k`), `pi`, `hermes` (`h`).
Providers: `anthropic`, `openai`, `go` (`opencode-go`), `openrouter` (`or`).
`sub` / `subscription` always means the tool's own subscription.

### Shims

`agentuse install-shims` writes short commands into `~/.local/bin`:

| Shim | Runs |
| --- | --- |
| `ccuse`, `cxuse`, `kuse`, `piuse`, `huse` | `agentuse use <tool> "$@"` |
| `<tool>-<provider>`, e.g. `claude-go`, `codex-or`, `kilo-openai` | `agentuse run <tool> <provider> -- "$@"` |
| with `--wrap`: `claude`, `codex`, … | `agentuse run <tool> default -- "$@"` |

The `--wrap` shims put the configured provider's key into plain launches.
That matters for Claude Code on OpenCode Go when you don't rely on
`apiKeyHelper`. When agentuse looks up the real binary, it skips its own
shims, so shadowing `claude` on `PATH` is safe. `uninstall-shims` only
removes files that agentuse wrote.

## The catalog

Built-in defaults ship with agentuse: providers, credentials, and a model
per harness and provider. Your file at `~/.config/agentuse/catalog.toml` (or
`$AGENTUSE_CATALOG`) is deep-merged on top, so it only needs what you change:

```toml
# A different model for Codex on OpenCode Go.
[tools.codex.providers.go]
model = "glm-5.3"

# Claude Code on Go: Sonnet-tier work on a bigger model.
[tools.claude.providers.go.env]
ANTHROPIC_DEFAULT_SONNET_MODEL = "kimi-k3"
```

Run `agentuse catalog` to see the merged result, and
[`default_catalog.toml`](src/agentuse/default_catalog.toml) for every key,
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
a command that calls `agentuse key <credential>` at request time: Codex's
`[model_providers.<id>.auth]` and Claude Code's `apiKeyHelper`. By default
it stores the absolute path of the agentuse that ran the switch. If you sync
those config files across machines, set `[settings] self = "agentuse"` so
they store the bare command name instead.

## Harness notes

What each permanent switch edits, and the traps it handles:

- **Claude Code**. Edits `settings.json` (`$CLAUDE_CONFIG_DIR`, default
  `~/.claude`): sets the `env` block (base URL and model tiers) and
  `apiKeyHelper`, so the VS Code extension and other bundled binaries get the
  key too. Your other `env` keys and `model` are left alone. Switching back to
  `anthropic` removes them, and only removes an `apiKeyHelper` that agentuse
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
  `model` pair; agentuse removes it.
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
  inputs.agentuse.url = "github:R3-da/agentuse";

  # in your home-manager configuration:
  imports = [ inputs.agentuse.homeManagerModules.default ];
  programs.agentuse = {
    enable = true;
    shims.wrap = true;               # claude/codex/... inject keys on launch
    settings = {
      credentials.opencode-go.sources = [ { file = "/run/secrets/opencode_go_api_key"; } ];
      tools.codex.providers.go.model = "glm-5.3";
    };
    # Or keep an editable catalog in your dotfiles instead of `settings`:
    # catalogFile = "${config.home.homeDirectory}/dotfiles/agentuse.toml";
  };
}
```

The module installs the package and builds the shims from the built-in
catalog plus `settings`. If you add providers only in a `catalogFile`, run
`agentuse install-shims` yourself to get their one-shot commands.
`nix build` runs the test suite.

## Development

```sh
uv run --with pytest python -m pytest      # or: nix flake check
```

The tests use fake harness binaries and a temporary `HOME`; they never touch
your real configuration.

## License

MIT
