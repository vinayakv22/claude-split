# Installing claude-split (instructions for AI agents)

You are installing **claude-split** for a user. It's a launcher for Claude Code
that keeps the main session on the user's Claude login and routes only subagent
requests to another Anthropic Messages-compatible provider. Follow these steps
in order. Don't improvise extra steps.

## Rules

- **Never ask the user to paste an API key into the chat**, and never echo, log, write to a file, or pass a key as a command-line argument. Keys reach the installer only through the `CLAUDE_SPLIT_API_KEY` environment variable, set by the user, or through the user typing it into the hidden prompt themselves.
- Don't use `sudo`. Everything installs per-user.
- Your shell probably has no TTY, so always use unattended mode (`--yes`). Interactive prompts are for the user's own terminal.

## 1. Check the platform

```bash
uname -s; uname -m
command -v python3 node claude curl
python3 --version; node --version
```

Supported platforms are macOS (arm64 or x86_64) and Linux (arm64 or x86_64)
with systemd user services. The installer needs Python 3.9+, Node.js 20+, and
Claude Code. On Linux, if Python or Node are missing or too old, ask the user
before installing them with their package manager. On macOS the installer
handles missing dependencies through Homebrew. If `claude` is missing, the
installer runs the official Claude Code installer, so mention that to the user
first.

## 2. Ask the user (one message, all questions)

1. **Provider**: one of `deepseek`, `anthropic`, `moonshot`, `zai`, `minimax`, `openrouter`, `local`, or a custom Anthropic Messages base URL. For a custom URL, also ask for the auth type: `x-api-key`, `bearer`, or `none`.
2. **Subagent model ID**, as the provider names it. If they don't know it, offer option B in step 3, which lists the provider's models interactively.
3. **Install the optional RTK compressor?** Default to no. It trims noisy tool output and downloads about 40 MB of pinned, checksum-verified binaries.
4. **How they want to supply the key**: A or B below.

## 3. Install

### Option A: the user exports the key, and you install unattended

Ask the user to run this in **their own terminal or session**, not through you.
In Claude Code they can type the line prefixed with `! `:

```bash
read -rs CLAUDE_SPLIT_API_KEY && export CLAUDE_SPLIT_API_KEY
```

If the variable isn't visible to your shell (check with
`test -n "$CLAUDE_SPLIT_API_KEY" && echo set`, which never prints the value),
fall back to option B. Otherwise run this, substituting the user's answers:

```bash
curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh \
  | CLAUDE_SPLIT_PROVIDER=<preset> CLAUDE_SPLIT_MODEL=<model-id> bash -s -- --yes [--rtk]
```

For a custom endpoint, replace `CLAUDE_SPLIT_PROVIDER=<preset>` with
`CLAUDE_SPLIT_BASE_URL=<url> CLAUDE_SPLIT_AUTH=<x-api-key|bearer|none>`.

### Option B: install now, and the user configures the provider themselves

```bash
curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh \
  | bash -s -- --yes --no-configure [--rtk]
```

Then tell the user to run this in their own terminal (in Claude Code:
`! ~/.local/bin/claude-split --configure-subagent`):

```bash
~/.local/bin/claude-split --configure-subagent
```

That command shows a provider menu, a hidden key prompt, and the provider's
live model list.

## 4. Verify

The installer exits non-zero if the installation failed, or if a requested
unattended provider configuration was not saved. Then:

```bash
~/.local/bin/claude-split --proxy-check
```

- A JSON response with `"subagent": {"ready": true, …}` means everything works.
- `subagent configuration/key is unavailable` means the provider isn't configured yet, so use option B.
- If Claude Code isn't logged in, the user must run `claude auth login` once in their own terminal.

## 5. Report back

Tell the user:

- To open a **new terminal** so PATH and completions load, then run `claude-split` exactly as they would run `claude`.
- `claude-split --rtk` uses RTK, if they chose to install it.
- `claude-split --configure-subagent` changes the provider, model, or key at any time.
- To uninstall: `curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh | bash -s -- --uninstall`

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Provider not configured: set CLAUDE_SPLIT_…` | A required variable is missing, so add it or use option B |
| `API key was rejected` / `model was not found` | Wrong key or model ID. Nothing was saved. Rerun with corrected values |
| `RTK is optional and not installed` | Rerun the installer with `--rtk`, or launch without `--rtk` |
| `could not start service` (Linux) | systemd user services are unavailable (some containers or WSL setups). Run in a normal login session |
