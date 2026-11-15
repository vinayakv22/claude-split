#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
ensure_brew() {
    if ! command -v brew >/dev/null; then
        echo 'Installing Homebrew (its installer may request your macOS password).'
        brew_installer="$(mktemp)"
        curl --fail --silent --show-error --location https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$brew_installer"
        /bin/bash "$brew_installer"
    fi
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
}
if [[ "$(uname -s)" == Darwin ]]; then
    if ! command -v python3 >/dev/null || ! python3 -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null; then
        ensure_brew
        brew install python
    fi
    if ! command -v node >/dev/null || ! node -e 'if (+process.versions.node.split(".")[0] < 20) process.exit(1)' 2>/dev/null; then
        ensure_brew
        brew install node
        export PATH="$(brew --prefix node)/bin:$PATH"
    fi
elif [[ "$(uname -s)" != Linux ]]; then
    echo 'Only macOS and Linux are supported.' >&2
    exit 1
fi
if ! command -v python3 >/dev/null || ! command -v node >/dev/null; then
    echo 'Install Python 3.9+ and Node.js 20+, then rerun this script.' >&2
    exit 1
fi
if ! command -v claude >/dev/null; then
    echo 'Installing Claude Code with the official native installer.'
    claude_installer="$(mktemp)"
    curl --fail --silent --show-error --location https://claude.ai/install.sh -o "$claude_installer"
    bash "$claude_installer"
fi
exec python3 "$SOURCE_DIR/install.py" "$@"
