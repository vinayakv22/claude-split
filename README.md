# Claude split

A personal Claude Code launcher: use your normal Claude login and main model,
route subagents to a configurable Anthropic Messages provider, and optionally
put both routes through local RTK request compression.

## Install on a Mac

Download **install-mac.sh** from this private repository and run it in Terminal:

```bash
bash ~/Downloads/install-mac.sh
```

The standalone script installs GitHub CLI if needed, asks you to sign into the
GitHub account with repository access, downloads this private repo, and runs
its installer. Homebrew may request your macOS password. Run without `sudo`.

Or, if GitHub CLI is already installed and authenticated:

```bash
gh repo clone vinayakv22/claude-split
cd claude-split
./install.sh
```

Supports Apple Silicon and Intel Macs. The installer installs missing Node.js
and Python through Homebrew, installs Claude Code using its official native
installer if absent, and installs pinned RTK + rtk-proxy v1.2.0 binaries with
SHA256 verification against GitHub release metadata. It needs internet access.
Existing RTK binaries in `~/.local/bin` are replaced with this pinned version;
use `./install.sh --skip-rtk` to keep your existing compatible binaries.

It installs zsh, Fish, and Bash completions and adds `~/.local/bin` to their PATH.
Shell configuration edits use marked blocks, are idempotent, and create backups
before changing existing files. Existing provider configuration and Claude
account data stay on the machine and are preserved. No keys are included here.

Open a **new terminal**, then:

```bash
claude auth login                         # if not already logged in
claude-split --configure-subagent
claude-split --proxy-check
claude-split --rtk --model sonnet
```

Use any main Claude model available to your account. Supply your actual
subagent model ID, endpoint, and API key during configuration. No paid provider
request is made by the installer itself; configuring a provider may incur usage.

## Routing and RTK

```text
claude-split       -> split proxy -> Anthropic (main) / provider (subagents)
claude-split --rtk -> RTK -> split proxy -> Anthropic / provider
```

Both services bind only to loopback: split proxy `127.0.0.1:3457`, RTK
`127.0.0.1:3458`. No Docker or hosted server is needed. Services start on demand
and do not start automatically at login. If RTK cannot start, `--rtk` fails
rather than silently bypassing it. Omitting the flag bypasses RTK even if its
service is still running.

The main route uses your normal Claude authentication. Without RTK, request
bodies and end-to-end identity/authentication headers pass through unchanged.
The internal `split-subagent` alias selects the provider route; that route
substitutes the configured model/key and removes Claude identity/authentication.
The launcher forces the alias for Claude Code subagents. Inline schemas in
`tool_addition` blocks are moved into top-level `tools` and replaced by named
`tool_reference` entries on the subagent route. This supports providers such as
DeepSeek that accept named tool additions but reject inline `tool_definition`.
Explicit top-level schemas take precedence over historical inline definitions;
main Claude requests retain their original format. Tool-schema regexes using
JavaScript's null-character escape `\0` are rewritten to equivalent `\x00`
escapes for provider compatibility. Literal escaped backslashes and schema
instance data (examples, defaults, constants, enums) are preserved.

RTK can modify main and subagent tool-result content. Default normalization
removes eligible ANSI styling, progress redraws, trailing whitespace, and
adjacent duplicate lines in larger tool results. Not every request shrinks,
and no fixed savings are promised. This installs the HTTP proxy integration,
not global RTK Claude hooks. Cache-breakpoint injection, credential borrowing,
and RTK context-retrieval compression are disabled. No extra model calls are
configured for compression. RTK is a separately licensed upstream dependency;
see [RTK](https://github.com/rtk-ai/rtk).

RTK's own context-retrieval feature happens to be called CCR; it is unrelated
to Claude Code Router. Neither is required here.

## Provider configuration

```bash
claude-split --configure-subagent
claude-split --configure-subagent --help
```

Supports Anthropic Messages endpoints, including CLIProxyAPI and other
compatible gateways, with `x-api-key`, `bearer`, or `none` authentication.
Accepts API roots, `/v1` bases, or full `/v1/messages` URLs. OpenAI-only endpoints
need a separate adapter. Gateways must support compatible Messages tools and SSE.

The hidden API-key prompt accepts a literal key, `$MY_API_KEY`, `${MY_API_KEY}`,
or `env:MY_API_KEY`. Export the variable first. Its value is safely resolved and
stored as the key, not as a live variable reference. Missing/empty variables
and shell expressions are rejected. `--api-key-stdin` accepts the same syntax.
Keep keys out of command-line arguments. For existing key files:

```bash
claude-split --configure-subagent \
  --model YOUR_MODEL --base-url http://127.0.0.1:8317/v1 \
  --auth bearer --key-file /absolute/path/to/key.txt
```

For a dotenv file, add `--key-env VARIABLE_NAME`. Paths are local to each
machine; configure again on a new Mac instead of copying Linux key-file paths.

Endpoint reachability, authentication, and model verification must pass before
saving. An authenticated model-catalog request checks that the model is listed.
If the catalog is unsupported, successful Messages output is required instead.
By default the check also requests a tool call, sends a tool result, and checks
streamed text. Messages tests can incur normal usage charges.

Only tool/usage failures **after** mandatory checks pass allow saving as
`unverified`. Invalid keys, unknown models, unreachable endpoints, and malformed
protocol responses preserve the previous config. An unfunded provider can save
if catalog verification passes; without a working catalog or successful model
response, verification cannot be completed and saving is blocked.

```bash
claude-split --configure-subagent --skip-check     # skip tools, still verify auth/model
claude-split --configure-subagent --require-check  # all checks must pass
```

These flags are mutually exclusive. Skipping tools can still require a tiny
billable Messages request if the provider lacks a catalog. Verification status
and individual check results are saved alongside the private configuration.
Checks have bounded deadlines, do not follow redirects, and do not print keys
or raw provider errors. `--proxy-check` only checks local readiness.

## Files and services

- Launcher: `~/.local/bin/claude-split`
- Runtime: `~/.local/share/claude-subagent-proxy/`
- Private provider config: `~/.config/claude-subagent-proxy/config.json`
- RTK usage data/logs: `~/.local/state/claude-split-rtk/`
- Mac LaunchAgents: `~/Library/LaunchAgents/io.claude-split.{proxy,rtk}.plist`
- Completions: standard per-user zsh, Fish, and Bash directories.

macOS status and stop commands:

```bash
launchctl print gui/$(id -u)/io.claude-split.proxy
launchctl print gui/$(id -u)/io.claude-split.rtk
launchctl kill SIGTERM gui/$(id -u)/io.claude-split.rtk
rtk-proxy stats --bind 127.0.0.1:3458
```

Rerun the installer to update files and register services. It can stop existing
proxy sessions during an upgrade; finish active sessions first. Runtime paths
are resolved during installation for Homebrew and native Claude installations.
Linux is also supported with existing Node.js 20+, Python 3.9+, and systemd user
services (`claude-subagent-proxy` and `claude-split-rtk`).

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 src/provider_check_test.py
node --test src/proxy.test.mjs src/rtk.test.mjs
```

Tests use local mock providers, including real RTK routing/compression and SSE;
they consume no paid API usage. Installer tests cover Apple Silicon/Intel target
selection, LaunchAgent generation, shell/config preservation, repeated installs,
archive checksum rejection, and platform-specific launcher commands. GitHub
Actions runs the suite on macOS and Linux. A real Claude subscription login and
a funded provider must be tested separately on your own Mac.
