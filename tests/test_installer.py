import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import runpy
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT/'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_platforms(self):
        self.assertEqual(installer.target_for('Darwin', 'arm64'), 'aarch64-apple-darwin')
        self.assertEqual(installer.target_for('Darwin', 'x86_64'), 'x86_64-apple-darwin')
        self.assertEqual(installer.target_for('Linux', 'aarch64'), 'aarch64-unknown-linux-musl')
        with self.assertRaises(ValueError): installer.target_for('Windows', 'amd64')

    def test_mac_install_preserves_config_is_idempotent_and_uses_portable_plists(self):
        with tempfile.TemporaryDirectory(prefix='split home ') as tmp:
            home = Path(tmp)
            config = home/'.config/claude-subagent-proxy/config.json'
            config.parent.mkdir(parents=True)
            original = '{"subagent":{"api_key":"mock-private-key"}}'
            config.write_text(original)
            (home/'.zshrc').write_text('# existing shell config\n')
            with patch.object(installer.shutil, 'which', side_effect=lambda cmd: '/opt/homebrew/bin/' + cmd), patch.object(installer.subprocess, 'check_output', return_value='v24.0.0'):
                for _ in range(2): installer.install(home, 'Darwin', 'arm64', rtk=False, activate=False)
            self.assertEqual(config.read_text(), original)
            self.assertEqual((home/'.zshrc').read_text().count(installer.MARKER), 1)
            self.assertIn('# existing shell config', (home/'.zshrc').read_text())
            self.assertTrue(list(home.glob('.zshrc.claude-split-backup-*')))
            for name in ('proxy', 'rtk'):
                data = plistlib.loads((home/f'Library/LaunchAgents/io.claude-split.{name}.plist').read_bytes())
                self.assertFalse(data['RunAtLoad'])
                self.assertEqual(data['KeepAlive'], {'Crashed': True})
                self.assertNotIn(str(Path.home()), str(data))
            for path in ('.config/fish/completions/claude-split.fish', '.local/share/zsh/site-functions/_claude-split', '.local/share/bash-completion/completions/claude-split'):
                self.assertIn('--rtk' if not path.endswith('.fish') else '-l rtk', (home/path).read_text())
            self.assertIn('/opt/homebrew/bin/claude', (home/'.local/share/claude-subagent-proxy/runtime.json').read_text())

    def test_rtk_checksums_and_safe_extraction(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            for name in ('rtk', 'rtk-proxy'):
                member = tarfile.TarInfo('../../escape/' + name)
                payload = b'#!/bin/sh\nexit 0\n'
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
        payload = data.getvalue()
        release = {'assets': [{'name': f'{name}-aarch64-apple-darwin.tar.gz', 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(), 'browser_download_url': 'https://example.test/' + name} for name in ('rtk', 'rtk-proxy')]}
        def response(request, **kwargs):
            url = request.full_url if hasattr(request, 'full_url') else request
            return io.BytesIO(json.dumps(release).encode() if 'api.github.com' in url else payload)
        with tempfile.TemporaryDirectory() as tmp, patch.object(installer.urllib.request, 'urlopen', side_effect=response):
            dest = Path(tmp)
            installer.install_rtk(dest, 'Darwin', 'arm64')
            self.assertTrue(os.access(dest/'rtk', os.X_OK))
            self.assertEqual({p.name for p in dest.iterdir()}, {'rtk', 'rtk-proxy'})
            release['assets'][0]['digest'] = 'sha256:' + '0' * 64
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch'): installer.install_rtk(dest, 'Darwin', 'arm64')

    def test_launchers_use_correct_services_and_forward_flags(self):
        class Executed(Exception): pass
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            claude = home/'mock-claude'
            claude.touch()
            runtime = home/'.local/share/claude-subagent-proxy/runtime.json'
            runtime.parent.mkdir(parents=True)
            runtime.write_text(json.dumps({'claude': str(claude)}))
            for system in ('Darwin', 'Linux'):
                for rtk in (False, True):
                    calls = []
                    def response(url, **kwargs):
                        data = {'subagent': {'ready': True}} if url.endswith('/healthz') else ({'anthropic_upstream': 'http://127.0.0.1:3457'} if url.endswith('/admin/settings') else {'status': 'ok'})
                        return io.BytesIO(json.dumps(data).encode())
                    def execute(binary, argv, env):
                        self.assertEqual(binary, str(claude))
                        self.assertEqual(argv[3:], ['--model', 'sonnet'])
                        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:' + ('3458' if rtk else '3457'))
                        self.assertEqual(env['CLAUDE_CODE_SUBAGENT_MODEL'], 'split-subagent')
                        self.assertNotIn('ANTHROPIC_API_KEY', env)
                        raise Executed()
                    def run(command, **kwargs):
                        calls.append(command)
                        return subprocess.CompletedProcess(command, 0)
                    with patch.object(Path, 'home', return_value=home), patch('platform.system', return_value=system), patch('subprocess.run', side_effect=run), patch('urllib.request.urlopen', side_effect=response), patch('os.execve', side_effect=execute), patch.object(sys, 'argv', ['claude-split', *(['--rtk'] if rtk else []), '--model', 'sonnet']):
                        with self.assertRaises(Executed): runpy.run_path(str(ROOT/'bin/claude-split'), run_name='__main__')
                    self.assertEqual(len(calls), 2 if rtk else 1)
                    if system == 'Darwin':
                        self.assertEqual(calls[0][:2], ['launchctl', 'kickstart'])
                        self.assertTrue(calls[0][2].endswith('/io.claude-split.proxy'))
                        if rtk: self.assertTrue(calls[1][2].endswith('/io.claude-split.rtk'))
                    else: self.assertEqual(calls[0], ['systemctl', '--user', 'start', 'claude-subagent-proxy.service'])

    def test_systemd_paths_with_spaces_and_specifiers(self):
        unit = installer.systemd_unit(['/tmp/a b/node', '/tmp/100%/proxy.mjs'], Path('/tmp/a b'), Path('/tmp/state'))
        self.assertIn('"/tmp/a b/node"', unit)
        self.assertIn('/tmp/100%%/proxy.mjs', unit)


if __name__ == '__main__': unittest.main()
