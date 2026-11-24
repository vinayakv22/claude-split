#!/usr/bin/env bash
# claude-split installer for macOS and Linux. Per-user, never needs sudo.
#
#   curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh | bash -s -- --yes --rtk
#   ./install.sh [--rtk | --no-rtk] [--configure | --no-configure] [--yes] [--uninstall]
#
# Run from a checkout it installs that checkout; piped from curl it downloads
# CLAUDE_SPLIT_REF (default: main) of CLAUDE_SPLIT_REPO first.
# Everything lives in main() so a truncated download never runs half a script.
set -euo pipefail

CLAUDE_SPLIT_WORKDIR=""
cleanup() { [[ -n "$CLAUDE_SPLIT_WORKDIR" ]] && rm -rf "$CLAUDE_SPLIT_WORKDIR"; return 0; }

main() {
    local repo="${CLAUDE_SPLIT_REPO:-vinayakv22/claude-split}" ref="${CLAUDE_SPLIT_REF:-main}"
    local yes=0 skip_deps=0 interactive=0 arg
    for arg in "$@"; do
        case "$arg" in
            -y|--yes) yes=1 ;;
            --uninstall|-h|--help) skip_deps=1 ;;
        esac
    done
    # Prompts read the terminal directly, so they also work under `curl | bash`.
    if (( ! yes )) && { : </dev/tty; } 2>/dev/null; then interactive=1; fi

    die() { echo "claude-split: $*" >&2; exit 1; }
    confirm() {  # Unattended runs accept; interactive runs default to yes.
        (( interactive )) || return 0
        local reply
        read -r -p "$1 [Y/n] " reply </dev/tty || reply=""
        [[ -z "$reply" || "$reply" == [Yy]* ]]
    }

    [[ "$(id -u)" != 0 ]] || die 'run this as your normal user, not root/sudo.'
    case "$(uname -s)" in Darwin|Linux) ;; *) die 'only macOS and Linux are supported.' ;; esac

    local source_dir="" script="${BASH_SOURCE[0]:-}"
    if [[ -n "$script" && -f "$script" ]]; then
        source_dir="$(cd -- "$(dirname -- "$script")" && pwd)"
    fi
    if [[ ! -f "$source_dir/install.py" ]]; then
        command -v curl >/dev/null || die 'curl is required.'
        command -v tar >/dev/null || die 'tar is required.'
        CLAUDE_SPLIT_WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/claude-split.XXXXXXXX")"
        trap cleanup EXIT
        echo "Downloading claude-split ($repo@$ref)..."
        curl -fsSL "https://github.com/$repo/archive/$ref.tar.gz" \
            | tar -xz --strip-components=1 -C "$CLAUDE_SPLIT_WORKDIR" \
            || die "could not download https://github.com/$repo (ref: $ref)."
        source_dir="$CLAUDE_SPLIT_WORKDIR"
    fi

    export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
    if (( ! skip_deps )); then
        ensure_dependencies
    fi

    if (( interactive )); then
        python3 -u "$source_dir/install.py" "$@" </dev/tty
    else
        python3 -u "$source_dir/install.py" "$@" </dev/null
    fi
}

python_ok() { command -v python3 >/dev/null && python3 -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null; }
node_ok() { command -v node >/dev/null && node -e 'process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)' 2>/dev/null; }

ensure_brew() {
    if ! command -v brew >/dev/null; then
        confirm 'Homebrew is needed to install missing dependencies. Install Homebrew now (may ask for your macOS password)?' \
            || die 'install Python 3.9+ and Node.js 20+, then rerun.'
        local brew_installer
        brew_installer="$(mktemp)"
        curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$brew_installer"
        /bin/bash "$brew_installer"
        rm -f "$brew_installer"
    fi
    if [[ -x /opt/homebrew/bin/brew ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then eval "$(/usr/local/bin/brew shellenv)"; fi
}

ensure_dependencies() {
    if [[ "$(uname -s)" == Darwin ]]; then
        if ! python_ok; then
            ensure_brew
            confirm 'Python 3.9+ is missing. Install it with Homebrew?' || die 'Python 3.9+ is required.'
            brew install python
        fi
        if ! node_ok; then
            ensure_brew
            confirm 'Node.js 20+ is missing. Install it with Homebrew?' || die 'Node.js 20+ is required.'
            brew install node
            export PATH="$(brew --prefix node)/bin:$PATH"
        fi
    fi
    python_ok || die 'Python 3.9+ is required. Install it with your package manager (e.g. apt install python3, pacman -S python), then rerun.'
    node_ok || die 'Node.js 20+ is required. Install it from https://nodejs.org or your package manager, then rerun.'
    if ! command -v claude >/dev/null; then
        confirm 'Claude Code is not installed. Install it with the official installer (https://claude.ai/install.sh)?' \
            || die 'Claude Code is required: https://docs.claude.com/claude-code'
        local claude_installer
        claude_installer="$(mktemp)"
        curl -fsSL https://claude.ai/install.sh -o "$claude_installer"
        bash "$claude_installer"
        rm -f "$claude_installer"
        command -v claude >/dev/null || die 'Claude Code installed, but `claude` is not on PATH yet. Open a new terminal and rerun.'
    fi
}

main "$@"
