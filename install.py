#!/usr/bin/env python3
"""Install Claude split per user. No credentials are read or copied."""
import argparse
import hashlib
import io
import json
import os
import platform
import plistlib
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parent
RTK_VERSION = 'v1.2.0'
MARKER = '# >>> claude-split >>>'
END = '# <<< claude-split <<<'


def target_for(system, machine):
    arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64', 'amd64': 'x86_64'}.get(machine.lower())
    if not arch or system not in ('Darwin', 'Linux'):
        raise ValueError('Supported platforms: Apple Silicon/Intel macOS and arm64/x86_64 Linux')
    return arch + ('-apple-darwin' if system == 'Darwin' else '-unknown-linux-musl')


def install_rtk(bin_dir, system, machine):
    target = target_for(system, machine)
    request = urllib.request.Request(f'https://api.github.com/repos/rtk-ai/rtk/releases/tags/{RTK_VERSION}',
                                     headers={'User-Agent': 'claude-split-installer'})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    for name in ('rtk', 'rtk-proxy'):
        asset_name = f'{name}-{target}.tar.gz'
        asset = next(a for a in release['assets'] if a['name'] == asset_name)
        digest = asset.get('digest', '')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError(f'No SHA256 digest available for {asset_name}')
        with urllib.request.urlopen(asset['browser_download_url'], timeout=120) as response:
            data = response.read()
        if 'sha256:' + hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Checksum mismatch for {asset_name}')
        # Extract only the expected regular file; never extract archive paths.
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = next(m for m in archive.getmembers() if m.isfile() and Path(m.name).name == name)
            content = archive.extractfile(member).read()
        temporary = bin_dir/(name + '.installing')
        temporary.write_bytes(content)
        temporary.chmod(0o755)
        temporary.replace(bin_dir/name)
        print(f'Installed {name} {RTK_VERSION}; SHA256 verified')


def update_block(path, body):
    text = path.read_text() if path.exists() else ''
    block = MARKER + '\n' + body.rstrip() + '\n' + END
    pattern = re.compile(re.escape(MARKER) + r'.*?' + re.escape(END), re.S)
    new = pattern.sub(lambda _: block, text) if MARKER in text else text.rstrip() + '\n\n' + block + '\n'
    if new != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_name(path.name + f'.claude-split-backup-{time.time_ns()}')
            shutil.copy2(path, backup)
        path.write_text(new)


def launch_agent(label, argv, home, state):
    return {
        'Label': label, 'ProgramArguments': argv, 'WorkingDirectory': str(home),
        'RunAtLoad': False, 'KeepAlive': {'Crashed': True}, 'ThrottleInterval': 3,
        'EnvironmentVariables': {'HOME': str(home), 'PATH': f'{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
        'StandardOutPath': str(state/(label + '.log')),
        'StandardErrorPath': str(state/(label + '.error.log')), 'Umask': 0o077,
    }


def service_commands(home, node):
    root = home/'.local/share/claude-subagent-proxy'
    state = home/'.local/state/claude-split-rtk'
    return {
        'proxy': [node, str(root/'proxy.mjs')],
        'rtk': [str(home/'.local/bin/rtk-proxy'), 'start', '--bind', '127.0.0.1:3458',
                '--anthropic-upstream', 'http://127.0.0.1:3457', '--normalize', 'true',
                '--cache-align', 'false', '--ccr', 'false', '--relay-borrowing', 'false',
                '--db', str(state/'usage.db')],
    }


def systemd_unit(argv, home, state, rtk=False):
    # systemd syntax differs from shell quoting. Escape specifiers and quoted paths.
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    dependency = 'Requires=claude-subagent-proxy.service\nAfter=claude-subagent-proxy.service\n' if rtk else ''
    return ('[Unit]\nDescription=Claude split ' + ('RTK' if rtk else 'proxy') + '\n' + dependency +
            '\n[Service]\nType=simple\nExecStart=' + ' '.join(quote(a) for a in argv) +
            '\nWorkingDirectory=' + quote(home) + '\nRestart=on-failure\nRestartSec=3\nUMask=0077\n')


def install_services(home, node, system, activate=True):
    state = home/'.local/state/claude-split-rtk'
    commands = service_commands(home, node)
    if system == 'Darwin':
        agents = home/'Library/LaunchAgents'
        agents.mkdir(parents=True, exist_ok=True)
        domain = f'gui/{os.getuid()}'
        for name, argv in commands.items():
            label = 'io.claude-split.' + name
            path = agents/(label + '.plist')
            if activate:
                subprocess.run(['launchctl', 'bootout', f'{domain}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            path.write_bytes(plistlib.dumps(launch_agent(label, argv, home, state)))
            if activate:
                subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
    else:
        units = home/'.config/systemd/user'
        units.mkdir(parents=True, exist_ok=True)
        for name, argv in commands.items():
            unit = 'claude-split-rtk' if name == 'rtk' else 'claude-subagent-proxy'
            (units/(unit + '.service')).write_text(systemd_unit(argv, home, state, name == 'rtk'))
        if activate:
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            # New units start on demand. Restart existing active instances on upgrade.
            for unit in ('claude-subagent-proxy', 'claude-split-rtk'):
                subprocess.run(['systemctl', '--user', 'try-restart', unit + '.service'], check=True)


def install(home, system, machine, *, rtk=True, activate=True):
    node = shutil.which('node')
    claude = shutil.which('claude')
    if not node or not claude:
        raise ValueError('Node.js and Claude Code must be installed; run ./install.sh')
    version = subprocess.check_output([node, '--version'], text=True).strip()
    if int(version.lstrip('v').split('.')[0]) < 20:
        raise ValueError('Node.js 20 or newer is required')
    target_for(system, machine)
    root = home/'.local/share/claude-subagent-proxy'
    bin_dir = home/'.local/bin'
    state = home/'.local/state/claude-split-rtk'
    for directory in (root, bin_dir, state, home/'.config/claude-subagent-proxy'):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('proxy.mjs', 'configure.py', 'provider_check.py'):
        shutil.copy2(SOURCE/'src'/name, root/name)
    launcher = (SOURCE/'bin/claude-split').read_text()
    # Pin the interpreter: launchd and new shells may not inherit Homebrew's PATH.
    launcher = '#!' + sys.executable + '\n' + launcher.split('\n', 1)[1]
    (bin_dir/'claude-split').write_text(launcher)
    (bin_dir/'claude-split').chmod(0o755)
    (root/'runtime.json').write_text(json.dumps({'claude': claude, 'node': node}, indent=2) + '\n')
    if rtk:
        install_rtk(bin_dir, system, machine)
    mappings = {
        'claude-split.fish': home/'.config/fish/completions/claude-split.fish',
        'claude-split.bash': home/'.local/share/bash-completion/completions/claude-split',
        '_claude-split': home/'.local/share/zsh/site-functions/_claude-split',
    }
    for source, dest in mappings.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE/'completions'/source, dest)
    bash = 'export PATH="$HOME/.local/bin:$PATH"\n[ -r "$HOME/.local/share/bash-completion/completions/claude-split" ] && source "$HOME/.local/share/bash-completion/completions/claude-split"'
    for filename in ('.bashrc', '.bash_profile'):
        update_block(home/filename, bash)
    update_block(home/'.zshrc', '''export PATH="$HOME/.local/bin:$PATH"
fpath=("$HOME/.local/share/zsh/site-functions" $fpath)
autoload -Uz compinit
(( $+functions[compdef] )) || compinit
autoload -Uz _claude-split
compdef _claude-split claude-split''')
    fish = home/'.config/fish/conf.d/claude-split.fish'
    fish.parent.mkdir(parents=True, exist_ok=True)
    fish.write_text('if not contains -- "$HOME/.local/bin" $PATH\n    set -gx PATH "$HOME/.local/bin" $PATH\nend\n')
    install_services(home, node, system, activate)
    print('Installed claude-split, completions, and on-demand services.')
    print('Open a new terminal, then run:')
    print('  claude auth login  # if not already logged in')
    print('  claude-split --configure-subagent')
    print('  claude-split --rtk')
    print('Existing provider configuration and Claude account data were preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-rtk', action='store_true', help='Keep existing RTK binaries')
    parser.add_argument('--no-services', action='store_true', help='Write services without registering them (testing/staging)')
    args = parser.parse_args()
    try:
        install(Path.home(), platform.system(), platform.machine(), rtk=not args.skip_rtk, activate=not args.no_services)
    except (OSError, ValueError, StopIteration, subprocess.CalledProcessError) as error:
        sys.exit(f'Installation failed: {error}')
