#!/usr/bin/env bash
# Standalone bootstrap for the private repository. Run this in Terminal, without sudo.
set -euo pipefail
if [[ "$(uname -s)" != Darwin ]]; then
    echo 'This bootstrap is for macOS. From a checkout on Linux, use ./install.sh.' >&2
    exit 1
fi
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v gh >/dev/null; then
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
    brew install gh
fi
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
    echo 'Sign into the GitHub account with access to vinayakv22/claude-split.'
    gh auth login --hostname github.com --git-protocol https --web
fi
checkout="$(mktemp -d "${TMPDIR:-/tmp}/claude-split.XXXXXXXX")"
# gh api uses your GitHub login for the private archive; no token in the URL.
gh api repos/vinayakv22/claude-split/tarball/main > "$checkout/source.tar.gz"
mkdir "$checkout/source"
tar -xzf "$checkout/source.tar.gz" --strip-components=1 -C "$checkout/source"
bash "$checkout/source/install.sh" "$@"
echo "Installer source retained at: $checkout/source"
