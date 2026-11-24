import contextlib
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
            self.assertFalse((home/'Library/LaunchAgents/io.claude-split.rtk.plist').exists())
            (home/'.local/bin/rtk-proxy').write_text('#!/bin/sh\n')
            with patch.object(installer.shutil, 'which', side_effect=lambda cmd: '/opt/homebrew/bin/' + cmd), patch.object(installer.subprocess, 'check_output', return_value='v24.0.0'):
                installer.install(home, 'Darwin', 'arm64', rtk=False, activate=False)
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
            (home/'.local/bin').mkdir(parents=True)
            (home/'.local/bin/rtk-proxy').touch()
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

    def test_rtk_flag_without_rtk_installed_explains_how_to_add_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            def response(url, **kwargs):
                return io.BytesIO(json.dumps({'subagent': {'ready': True}}).encode())
            with patch.object(Path, 'home', return_value=home), patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)), patch('urllib.request.urlopen', side_effect=response), patch.object(sys, 'argv', ['claude-split', '--rtk']):
                with self.assertRaises(SystemExit) as exit:
                    runpy.run_path(str(ROOT/'bin/claude-split'), run_name='__main__')
            self.assertIn('--rtk', str(exit.exception.code))
            self.assertIn('not installed', str(exit.exception.code))

    def install_mock(self, home, system='Linux'):
        with patch.object(installer.shutil, 'which', side_effect=lambda cmd: '/usr/bin/' + cmd), patch.object(installer.subprocess, 'check_output', return_value='v24.0.0'), contextlib.redirect_stdout(io.StringIO()):
            installer.install(home, system, 'x86_64', rtk=False, activate=False)

    def test_uninstall_removes_install_but_keeps_config_and_user_shell_lines(self):
        for system in ('Linux', 'Darwin'):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                (home/'.bashrc').write_text('alias ll="ls -l"\n')
                config = home/'.config/claude-subagent-proxy/config.json'
                config.parent.mkdir(parents=True)
                config.write_text('{}')
                self.install_mock(home, system)
                with contextlib.redirect_stdout(io.StringIO()):
                    installer.uninstall(home, system, activate=False)
                self.assertFalse((home/'.local/bin/claude-split').exists())
                self.assertFalse((home/'.local/share/claude-subagent-proxy').exists())
                self.assertFalse(any((home/f).exists() for f in installer.SERVICE_FILES[system]))
                self.assertEqual((home/'.bashrc').read_text(), 'alias ll="ls -l"\n')
                self.assertNotIn(installer.MARKER, (home/'.zshrc').read_text())
                self.assertTrue(config.exists())

    def test_unattended_main_defaults_to_no_rtk_and_no_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            calls = []
            with patch.object(Path, 'home', return_value=home), patch.object(installer, 'install', side_effect=lambda *a, **k: calls.append(k)), patch.object(installer, 'run_configuration') as configure, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installer.main(['--yes', '--no-services'], environ={}), 0)
            self.assertFalse(calls[0]['rtk'])
            configure.assert_not_called()

    def test_api_key_is_passed_by_variable_name_never_in_argv(self):
        values = installer.provider_env({'CLAUDE_SPLIT_PROVIDER': 'deepseek', 'CLAUDE_SPLIT_MODEL': 'm', 'CLAUDE_SPLIT_API_KEY': 'secret-value', 'OTHER': 'x'})
        argv = installer.configure_command(Path('/h'), values)
        self.assertNotIn('secret-value', ' '.join(argv))
        self.assertEqual(argv[-6:], ['--provider', 'deepseek', '--model', 'm', '--api-key-env', 'CLAUDE_SPLIT_API_KEY'])
        with patch.object(installer.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(installer.run_configuration(Path('/h'), {'MODEL': 'm'}, False, {}))
        run.assert_not_called()

    def test_systemd_paths_with_spaces_and_specifiers(self):
        unit = installer.systemd_unit(['/tmp/a b/node', '/tmp/100%/proxy.mjs'], Path('/tmp/a b'), Path('/tmp/state'))
        self.assertIn('"/tmp/a b/node"', unit)
        self.assertIn('/tmp/100%%/proxy.mjs', unit)


if __name__ == '__main__': unittest.main()
