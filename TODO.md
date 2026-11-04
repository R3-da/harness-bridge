# TODO

## Add API keys and log in from hbridge itself

Today a user has to export environment variables, run `opencode auth login`,
or edit the catalog before a provider works. Make both possible from hbridge,
from the command line and from `hbridge ui`.

### Command line

- [ ] `hbridge key set <credential>`: prompt for the key with hidden input (or
      read it from stdin, for scripts), store it, and print where it went.
- [ ] `hbridge key remove <credential>`, and `hbridge key list` showing each
      credential's source without ever printing the value. (Today
      `hbridge key <credential>` prints a key for Codex auth commands and
      `apiKeyHelper`; keep that working, or move it to `hbridge key get`.)
- [ ] Storage: the OS keychain first (macOS Keychain via `security`, Linux
      Secret Service via `secret-tool`), with a `0600` file under
      `~/.config/hbridge/` as the fallback. Expose it as a new credential
      source kind (for example `{ keychain = "opencode-go" }`) and add it to
      the built-in sources.
- [ ] Option to also write OpenCode's `auth.json`, so OpenCode shares the key.
- [ ] `hbridge login <tool>`: run the harness's own subscription login (for
      example `codex login`) instead of documenting it per harness. Confirm
      each harness's exact login command first.
- [ ] Show subscription login state in `hbridge status` and `hbridge doctor`,
      for example whether Codex's `auth.json` holds a ChatGPT login.

### Routing page (`hbridge ui`)

- [ ] "Add key" on provider cards that show "no key found": a masked input
      that posts to the local server. The key is never echoed back to the
      page.
- [ ] "Replace key" and "Remove key" on cards that already have one.
- [ ] "Log in" on subscription cards: start the harness's login flow, or show
      the command to copy when it needs a terminal.
- [ ] Show each subscription's login state on its card.

### Security requirements

- [ ] Keys only travel over the loopback server, with the existing token and
      `Host` checks; requests carrying keys are never logged.
- [ ] Tests assert that no key value ever appears in `/api/state`, in error
      messages, or in any config file hbridge writes.

## Later

- [ ] `hbridge check [tool] [provider]`: a routing smoke test that sends a
      tiny prompt through each installed harness and reports the model that
      answered (Codex's `model:`/`provider:` header, Kilo's `> code · <model>`
      line, Claude Code's `modelUsage`, Hermes's `init` event).
- [ ] Publish to PyPI as `harness-bridge`.
- [ ] Native Windows support (the shims are POSIX shell scripts today).
