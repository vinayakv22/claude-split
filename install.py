#!/usr/bin/env python3
"""Install claude-split for the current user (macOS/Linux, no sudo).

Interactive by default; pass --yes (or run without a terminal) for unattended installs.
Unattended provider setup reads CLAUDE_SPLIT_PROVIDER / CLAUDE_SPLIT_BASE_URL /
CLAUDE_SPLIT_AUTH / CLAUDE_SPLIT_MODEL / CLAUDE_SPLIT_API_KEY from the environment.
"""
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
REPO_URL = 'https://github.com/vinayakv22/claude-split'
ONE_LINER = 'curl -fsSL https://raw.githubusercontent.com/vinayakv22/claude-split/main/install.sh | bash'


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


def remove_block(path):
    if not path.exists() or MARKER not in path.read_text():
        return
    text = path.read_text()
    shutil.copy2(path, path.with_name(path.name + f'.claude-split-backup-{time.time_ns()}'))
    pattern = re.compile(r'\n*' + re.escape(MARKER) + r'.*?' + re.escape(END) + r'\n?', re.S)
    path.write_text(pattern.sub('\n', text).rstrip('\n') + '\n')


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
    if not (home/'.local/bin/rtk-proxy').is_file():
        del commands['rtk']  # RTK is optional; only register it when installed.
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
            for name in commands:
                unit = 'claude-split-rtk' if name == 'rtk' else 'claude-subagent-proxy'
                subprocess.run(['systemctl', '--user', 'try-restart', unit + '.service'], check=True)


def install(home, system, machine, *, rtk=False, activate=True):
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
    print('Installed claude-split, shell completions, and on-demand services.')
    print('RTK: ' + ('installed (use claude-split --rtk)' if (bin_dir/'rtk-proxy').is_file() else 'not installed (optional)'))


SERVICE_FILES = {
    'Darwin': ['Library/LaunchAgents/io.claude-split.proxy.plist', 'Library/LaunchAgents/io.claude-split.rtk.plist'],
    'Linux': ['.config/systemd/user/claude-subagent-proxy.service', '.config/systemd/user/claude-split-rtk.service'],
}


def uninstall(home, system, activate=True):
    """Remove what install() added. Provider config, RTK binaries and usage data are kept."""
    if activate and system == 'Darwin':
        for label in ('io.claude-split.proxy', 'io.claude-split.rtk'):
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif activate:
        subprocess.run(['systemctl', '--user', 'disable', '--now', 'claude-split-rtk.service', 'claude-subagent-proxy.service'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for relative in SERVICE_FILES.get(system, []) + [
            '.local/bin/claude-split', '.config/fish/conf.d/claude-split.fish',
            '.config/fish/completions/claude-split.fish', '.local/share/bash-completion/completions/claude-split',
            '.local/share/zsh/site-functions/_claude-split']:
        (home/relative).unlink(missing_ok=True)
    shutil.rmtree(home/'.local/share/claude-subagent-proxy', ignore_errors=True)
    if activate and system == 'Linux':
        subprocess.run(['systemctl', '--user', 'daemon-reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for filename in ('.bashrc', '.bash_profile', '.zshrc'):
        remove_block(home/filename)
    print('Removed claude-split, its services, completions, and shell blocks.')
    print('Kept (delete manually if unwanted):')
    print(f'  provider config + key: {home}/.config/claude-subagent-proxy/')
    print(f'  RTK binaries:          {home}/.local/bin/rtk, {home}/.local/bin/rtk-proxy')
    print(f'  RTK usage data:        {home}/.local/state/claude-split-rtk/')


def prompt_yes(question, default):
    suffix = ' [Y/n] ' if default else ' [y/N] '
    while True:
        answer = input(question + suffix).strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes'):
            return True
        if answer in ('n', 'no'):
            return False


def provider_env(environ):
    names = ('PROVIDER', 'BASE_URL', 'AUTH', 'MODEL', 'API_KEY')
    return {name: environ['CLAUDE_SPLIT_' + name].strip() for name in names if environ.get('CLAUDE_SPLIT_' + name, '').strip()}


def configure_command(home, values):
    """Build the configure.py argv from CLAUDE_SPLIT_* values. The key goes to stdin, never argv."""
    argv = [sys.executable, str(home/'.local/share/claude-subagent-proxy/configure.py')]
    for name, flag in (('PROVIDER', '--provider'), ('BASE_URL', '--base-url'), ('AUTH', '--auth'), ('MODEL', '--model')):
        if name in values:
            argv += [flag, values[name]]
    if 'API_KEY' in values:
        argv += ['--api-key-env', 'CLAUDE_SPLIT_API_KEY']
    return argv


def run_configuration(home, values, interactive, environ):
    argv = configure_command(home, values)
    if not interactive:
        missing = [n for n in ('MODEL',) if n not in values]
        if 'PROVIDER' not in values and 'BASE_URL' not in values:
            missing.append('PROVIDER (or CLAUDE_SPLIT_BASE_URL)')
        if 'API_KEY' not in values and values.get('AUTH') != 'none':
            missing.append('API_KEY')
        if missing:
            print('Provider not configured: set ' + ', '.join('CLAUDE_SPLIT_' + m for m in missing) +
                  ' or run claude-split --configure-subagent later.', file=sys.stderr)
            return False
    result = subprocess.run(argv, env=dict(environ), stdin=None if interactive else subprocess.DEVNULL)
    return result.returncode == 0


def main(argv=None, environ=os.environ):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    rtk = parser.add_mutually_exclusive_group()
    rtk.add_argument('--rtk', dest='rtk', action='store_true', default=None, help='Install the optional pinned RTK request compressor')
    rtk.add_argument('--no-rtk', '--skip-rtk', dest='rtk', action='store_false', help='Do not install RTK (existing RTK binaries are left alone)')
    configure = parser.add_mutually_exclusive_group()
    configure.add_argument('--configure', dest='configure', action='store_true', default=None, help='Configure the subagent provider after installing')
    configure.add_argument('--no-configure', dest='configure', action='store_false', help='Skip provider configuration')
    parser.add_argument('-y', '--yes', action='store_true', help='Never prompt; use flags, CLAUDE_SPLIT_* variables, and defaults')
    parser.add_argument('--uninstall', action='store_true', help='Remove claude-split (keeps provider config and RTK binaries)')
    parser.add_argument('--no-services', action='store_true', help='Write services without registering them (testing/staging)')
    args = parser.parse_args(argv)
    home, system = Path.home(), platform.system()
    if args.uninstall:
        uninstall(home, system, activate=not args.no_services)
        return 0
    interactive = sys.stdin.isatty() and not args.yes
    values = provider_env(environ)
    print('claude-split installer: your Claude login for the main session, another provider for subagents.')
    if args.rtk is None:
        args.rtk = False
        if interactive:
            print('\nOptional: RTK (https://github.com/rtk-ai/rtk) is a local proxy that trims noisy tool output')
            print('(ANSI codes, progress bars, duplicate lines) before requests leave your machine.')
            print('It downloads two pinned, SHA256-verified binaries (~40 MB). You can add it later with --rtk.')
            args.rtk = prompt_yes('Install RTK?', False)
    install(home, system, platform.machine(), rtk=args.rtk, activate=not args.no_services)
    configured = (home/'.config/claude-subagent-proxy/config.json').exists()
    if args.configure is None:
        if values:
            args.configure = True
        elif interactive:
            args.configure = prompt_yes('Configure the subagent provider now (needs its API key)?', not configured)
        else:
            args.configure = False
    ok = True
    if args.configure:
        print('\nConfiguring the subagent provider (key is verified live, never printed).')
        ok = run_configuration(home, values, interactive, environ)
        if not ok:
            print('Provider configuration was not saved. Retry with: claude-split --configure-subagent', file=sys.stderr)
        configured = configured or ok
    print('\nNext steps (open a new terminal first so PATH and completions load):')
    print('  claude auth login               # if Claude Code is not logged in yet')
    if not configured:
        print('  claude-split --configure-subagent')
    print('  claude-split' + (' --rtk' if (home/'.local/bin/rtk-proxy').is_file() else '') + '                 # use it like `claude`')
    print('Docs: ' + REPO_URL)
    return 0 if ok or interactive else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, StopIteration, subprocess.CalledProcessError) as error:
        sys.exit(f'Installation failed: {error}')
    except (KeyboardInterrupt, EOFError):
        sys.exit('\nInstallation cancelled.')
