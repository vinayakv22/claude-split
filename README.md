# claude-split

**Keep your main Claude Code conversation on your Claude subscription, and run
subagents on a different provider such as DeepSeek, Kimi, GLM, MiniMax,
OpenRouter, or your own gateway.**

`claude-split` is a drop-in launcher for `claude`. It starts a small local
proxy that leaves your main session untouched (same login, same model) and
reroutes only subagent requests to an Anthropic Messages-compatible provider
that you choose. Subagents do most of the bulk reading and searching, so this
can save a lot of subscription quota.

```text
claude-split        ─► local split proxy ─┬─► Anthropic (main session, your normal login)
                                          └─► your provider (subagents only)
claude-split --rtk  ─► RTK compressor ─► split proxy ─► …   (optional)
```

- Runs on macOS (Apple Silicon or Intel) and Linux (systemd user services). Never needs sudo.
- Everything binds to `127.0.0.1`. You don't need Docker or a hosted server, and nothing starts at login.
- Your Claude login token is never read, stored, or forwarded to the subagent provider.
- [RTK](https://github.com/rtk-ai/rtk) request compression is **optional**, and the installer asks whether you want it.

## Install

### 1. Interactive one-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh | bash
```

The installer:

1. Checks for Python 3.9+, Node.js 20+, and Claude Code. On macOS it offers to install missing ones with Homebrew, and it offers the official Claude Code installer.
2. Asks whether to install the optional RTK compressor (default: **no**).
3. Asks whether to configure the subagent provider now. You pick a provider preset, paste its API key into a hidden prompt, and choose a model from the provider's live model list. The key is verified before anything is saved.

### 2. Unattended, with an API key

For CI, dotfiles, or scripted setups. Pass the provider settings as environment
variables on the `bash` side of the pipe. The key is handed to the configurator
by variable name, so it never shows up in process arguments or output.

```bash
read -rs CLAUDE_SPLIT_API_KEY && export CLAUDE_SPLIT_API_KEY   # paste key, press Enter (bash/zsh)
curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh \
  | CLAUDE_SPLIT_PROVIDER=deepseek CLAUDE_SPLIT_MODEL=<model-id> bash -s -- --yes
```

| Variable | Meaning |
| --- | --- |
| `CLAUDE_SPLIT_PROVIDER` | Preset name (see [providers](#providers)), **or** set `CLAUDE_SPLIT_BASE_URL` |
| `CLAUDE_SPLIT_BASE_URL` | Any Anthropic Messages endpoint (overrides the preset URL) |
| `CLAUDE_SPLIT_AUTH` | `x-api-key`, `bearer`, or `none` (overrides the preset) |
| `CLAUDE_SPLIT_MODEL` | Provider model ID used for subagents (required) |
| `CLAUDE_SPLIT_API_KEY` | Provider API key (not needed with `AUTH=none`) |

Add `--rtk` to also install RTK.

### 3. Let your coding agent install it

Paste this to Claude Code, Codex, Cursor, or any agent with shell access:

> Install claude-split by following https://github.com/vinayakv22/claude-split/blob/main/INSTALL.md

[INSTALL.md](INSTALL.md) is written for agents. It tells them to ask you for
the provider, model, and RTK choice, and keeps your key out of their transcript.

### 4. From a clone

```bash
git clone https://github.com/vinayakv22/claude-split
cd claude-split
./install.sh            # same interactive installer
```

### Installer options

```text
--rtk / --no-rtk              install the optional RTK compressor, or don't (default: ask; unattended: no)
--configure / --no-configure  configure the provider after installing (default: ask; unattended: only if CLAUDE_SPLIT_* set)
-y, --yes                     never prompt (also automatic when there is no terminal)
--uninstall                   remove claude-split (keeps your provider config and RTK binaries)
```

To pass options through the one-liner, use `curl … | bash -s -- --rtk --yes`.
Set `CLAUDE_SPLIT_REF=v1.0.0` to install a tag or branch other than `main`.
Rerunning the installer upgrades in place and keeps your configuration. Shell
rc edits are idempotent marked blocks, and a backup is taken first.

## Usage

Open a **new terminal** after installing, then:

```bash
claude auth login                 # once, if Claude Code isn't logged in yet
claude-split                      # use exactly like `claude`; all flags pass through
claude-split --model opus         # any main model your account can use
claude-split --rtk                # route through RTK (if installed)
claude-split --configure-subagent # change provider / model / key at any time
claude-split --proxy-check        # local readiness status (JSON)
claude-split --proxy-help
```

Completions are installed for bash, zsh, and fish.

## Providers

Presets are starting points. Every configuration is verified live before it
is saved, and you can override the URL and auth type of any preset.

| Preset | Base URL | Auth |
| --- | --- | --- |
| `deepseek` | `https://api.deepseek.com/anthropic` | `x-api-key` |
| `anthropic` | `https://api.anthropic.com` (a separate API key) | `x-api-key` |
| `moonshot` | `https://api.moonshot.ai/anthropic` | `bearer` |
| `zai` | `https://api.z.ai/api/anthropic` | `bearer` |
| `minimax` | `https://api.minimax.io/anthropic` | `bearer` |
| `openrouter` | `https://openrouter.ai/api` | `bearer` |
| `local` | `http://127.0.0.1:8317/v1` (CLIProxyAPI or similar) | `bearer` |
| custom | any Anthropic Messages endpoint | any |

The provider must speak the **Anthropic Messages API** with tools and SSE
streaming. OpenAI-only endpoints need a separate adapter. API roots, `/v1`
bases, and full `/v1/messages` URLs are all accepted.

```bash
claude-split --configure-subagent                                     # interactive menu
claude-split --configure-subagent --provider zai --model <model-id>  # prompts only for the key
claude-split --configure-subagent --help
```

**Ways to supply the key.** By default you get a hidden prompt, which also
accepts `$VAR`, `${VAR}`, or `env:VAR`. The alternatives are
`--api-key-env VAR`, `--api-key-stdin`, or `--key-file /abs/path` (add
`--key-env NAME` for a dotenv file). Keys are never accepted as command-line
values, and are stored in a `0700` directory.

**Verification.** Before saving, claude-split checks reachability,
authentication, and the model, using the provider's model catalog where one
exists and a tiny Messages request otherwise. It then runs a streamed tool
round trip. If authentication or the model check fails, nothing is saved and
the previous configuration is kept. If only the tool check fails (for example
an unfunded account), the configuration is saved as `unverified`. Use
`--skip-check` to skip the tool test, or `--require-check` to make every check
mandatory. Messages-based checks can incur a few tokens of usage. Checks never
follow redirects and never print keys or raw provider errors.

## How routing works

The launcher sets `ANTHROPIC_BASE_URL` to the local proxy and forces
Claude Code's subagent model to the internal alias `split-subagent`:

- **Main requests** pass through to Anthropic unchanged, with your normal Claude authentication. Inherited `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock, and Vertex variables are cleared for the session.
- **`split-subagent` requests** get your configured model and key, and all Claude identity and authentication headers are stripped before they leave your machine.
- Some providers (DeepSeek, for example) reject the inline `tool_definition` schemas that Claude Code sends to subagents. On the subagent route only, these are moved into top-level `tools`, and `\0` regex escapes are rewritten as `\x00`. Main requests keep their original format.

## RTK (optional)

[RTK](https://github.com/rtk-ai/rtk) is a separately licensed local proxy. It
trims noisy tool output (ANSI styling, progress redraws, trailing whitespace,
and adjacent duplicate lines in larger tool results) from both main and
subagent requests. Savings vary and are not guaranteed. claude-split installs
pinned `rtk` and `rtk-proxy` v1.2.0 binaries and verifies their SHA256 against
GitHub release metadata. It wires up only the HTTP proxy integration, with
cache-breakpoint injection, credential borrowing, and context-retrieval (CCR)
compression all disabled. No extra model calls are made.

- Add it later: rerun the installer with `--rtk`.
- If RTK can't start, `claude-split --rtk` fails rather than silently bypassing it. Without `--rtk`, RTK is never used.
- `--no-rtk` never deletes RTK binaries you already have. If they're present, the RTK service stays registered.

## Files and services

| What | Where |
| --- | --- |
| Launcher | `~/.local/bin/claude-split` |
| Runtime | `~/.local/share/claude-subagent-proxy/` |
| Provider config + key (private) | `~/.config/claude-subagent-proxy/config.json` |
| RTK binaries / usage data | `~/.local/bin/rtk{,-proxy}`, `~/.local/state/claude-split-rtk/` |
| macOS services | `~/Library/LaunchAgents/io.claude-split.{proxy,rtk}.plist` |
| Linux services | `~/.config/systemd/user/{claude-subagent-proxy,claude-split-rtk}.service` |

The split proxy listens on `127.0.0.1:3457` and RTK on `127.0.0.1:3458`.
Services start on demand when you run `claude-split`, and are restarted on
upgrade, so finish active sessions before you rerun the installer.

```bash
# Linux
systemctl --user status claude-subagent-proxy claude-split-rtk
systemctl --user stop claude-subagent-proxy claude-split-rtk
# macOS
launchctl print gui/$(id -u)/io.claude-split.proxy
launchctl kill SIGTERM gui/$(id -u)/io.claude-split.proxy
```

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh | bash -s -- --uninstall
```

This removes the launcher, runtime, services, completions, and shell blocks.
Your provider config (including the key), RTK binaries, and RTK usage data are
kept, and their paths are printed so you can delete them yourself.

## Development

```bash
python3 -m unittest discover -s tests -v
(cd src && python3 provider_check_test.py)
node --test src/proxy.test.mjs src/rtk.test.mjs   # rtk.test.mjs needs RTK in ~/.local/bin
```

The tests use local mock providers, including real RTK routing and SSE, and
make no paid API calls. GitHub Actions runs them on macOS and Linux.

## Disclaimer

This is an independent project, not affiliated with or endorsed by Anthropic
or any provider listed here. You're responsible for complying with the terms of
your Claude plan and of each provider you route traffic to. Subagent prompts,
including file contents your agents read, are sent to the provider you
configure.

## License

[MIT](LICENSE). RTK is a separate project under its own license.
