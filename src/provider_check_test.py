import contextlib
import io
from unittest.mock import patch
import configure as configuration
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from provider_check import ProviderCheckError, check_provider, messages_url, stream_message

ROOT = Path(__file__).parent
KEY = 'private-verification-test-key'


def event(kind, **data):
    return ('event: '+kind+'\ndata: '+json.dumps({'type': kind, **data})+'\n\n').encode()


def successful_stream(tool=True):
    result = event('message_start', message={'type': 'message', 'role': 'assistant', 'content': []})
    if tool:
        result += event('content_block_start', index=0, content_block={'type': 'tool_use', 'id': 'probe-call', 'name': 'split_connection_check', 'input': {}})
        for part in ['{', '}']:
            result += event('content_block_delta', index=0, delta={'type': 'input_json_delta', 'partial_json': part})
    else:
        result += event('content_block_start', index=0, content_block={'type': 'text', 'text': ''})
        result += event('content_block_delta', index=0, delta={'type': 'text_delta', 'text': 'SPLIT_CHECK_OK'})
    result += event('content_block_stop', index=0)
    result += event('message_delta', delta={'stop_reason': 'tool_use' if tool else 'end_turn'})
    return result + event('message_stop')


@contextlib.contextmanager
def provider(mode='success'):
    class Captured(list):
        def __init__(self):
            super().__init__()
            self.gets = []
    captured = Captured()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            captured.gets.append(self.path)
            status = 200
            if mode in ('unauthorized', 'catalog401'): status = 401
            elif mode == 'quota-before-catalog': status = 402
            elif mode.startswith('catalog-missing'): status = 404
            payload = {'data': [{'id': m} for m in ('configured-model', 'm', 'worker')]}
            if mode == 'bad-model': payload = {'data': []}
            data = json.dumps(payload if status == 200 else {'error': {'message': KEY}}).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            captured.append({'path': self.path, 'headers': self.headers, 'body': body})
            status, content_type = 200, 'text/event-stream'
            if mode in ('no-balance', 'catalog-missing-no-balance'):
                status, content_type = 402, 'application/json'
                data = json.dumps({'error': {'message': KEY}}).encode()
            elif mode in ('unauthorized', 'second-fails') and (mode == 'unauthorized' or len(captured) == 2):
                status, content_type = 401, 'application/json'
                data = json.dumps({'error': {'message': KEY}}).encode()
            elif mode in ('tool400', 'catalog-missing-tool400') and body.get('tools'):
                status, content_type, data = 400, 'application/json', b'{}'
            elif mode == 'catalog-missing-tool400': data = successful_stream(False)
            elif mode == 'redirect':
                self.send_response(302); self.send_header('Location', '/stolen-key'); self.end_headers(); return
            elif mode == 'json':
                content_type, data = 'application/json', b'{"type":"message"}'
            elif mode == 'malformed': data = b'data: not-json\n\n'
            elif mode == 'openai': data = b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
            elif mode == 'error-event': data = event('error', error={'message': KEY})
            elif mode == 'slow':
                self.send_response(200); self.send_header('Content-Type', content_type); self.end_headers()
                self.wfile.write(b': connected\n\n'); self.wfile.flush(); time.sleep(0.6); return
            elif mode == 'no-tool': data = successful_stream(False)
            else: data = successful_stream(len(captured) == 1)
            self.send_response(status); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(data))); self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', captured
    finally: server.shutdown(); server.server_close(); thread.join()


class ProviderCheckTests(unittest.TestCase):
    def config(self, url, auth='x-api-key'):
        return {'base_url': url, 'model': 'configured-model', 'auth_type': auth, 'api_key': KEY}

    def cli(self, home, url, *extra):
        return subprocess.run([sys.executable, str(ROOT/'configure.py'), '--model', 'configured-model', '--base-url', url,
            '--auth', 'bearer', '--api-key-stdin', *extra], input=KEY+'\n', text=True, capture_output=True, timeout=10,
            env={**os.environ, 'HOME': home})

    def test_live_protocol_auth_and_tool_result(self):
        for auth in ('x-api-key', 'bearer', 'none'):
            with self.subTest(auth=auth), provider() as (url, calls):
                check_provider(self.config(url+'/gateway/v1', auth))
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(c['path'] == '/gateway/v1/messages' and c['body']['model'] == 'configured-model' and c['body']['stream'] for c in calls))
                self.assertEqual(calls[0]['headers'].get('X-Api-Key'), KEY if auth == 'x-api-key' else None)
                self.assertEqual(calls[0]['headers'].get('Authorization'), 'Bearer '+KEY if auth == 'bearer' else None)
                self.assertEqual(calls[1]['body']['messages'][-1]['content'][0]['tool_use_id'], 'probe-call')
                self.assertEqual(calls[1]['body']['messages'][-1]['content'][0]['type'], 'tool_result')

    def test_cli_only_saves_after_success_and_keeps_key_private(self):
        with tempfile.TemporaryDirectory() as home, provider() as (url, calls):
            result = self.cli(home, url)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(KEY, result.stdout+result.stderr)
            self.assertIn('Provider verification passed', result.stdout)
            path = Path(home)/'.config/claude-subagent-proxy/config.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['subagent']['api_key'], KEY)
            self.assertEqual(len(calls), 2)

    def test_failures_preserve_previous_config_and_do_not_leak_provider_body(self):
        for mode in ('unauthorized', 'second-fails', 'json', 'malformed', 'openai', 'error-event', 'no-tool', 'redirect'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home, provider(mode) as (url, calls):
                path = Path(home)/'.config/claude-subagent-proxy/config.json'
                path.parent.mkdir(parents=True); path.write_text('{"subagent":{"model":"previous-model"}}\n'); previous = path.read_bytes()
                result = self.cli(home, url, '--require-check')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_bytes(), previous)
                self.assertNotIn(KEY, result.stdout+result.stderr)
                self.assertIn('Configuration not saved', result.stderr)
                self.assertFalse(list(path.parent.glob('.config-*')))
                if mode == 'redirect': self.assertEqual(len(calls), 1)

    def test_invalid_key_file_does_not_contact_provider(self):
        with tempfile.TemporaryDirectory() as home, provider() as (url, calls):
            keyfile = Path(home)/'empty-key';keyfile.write_text('')
            result = subprocess.run([sys.executable, str(ROOT/'configure.py'), '--model', 'm', '--base-url', url,
                '--auth', 'x-api-key', '--key-file', str(keyfile), '--require-check'], text=True,capture_output=True, env={**os.environ,'HOME':home})
            self.assertNotEqual(result.returncode, 0);self.assertEqual(calls, [])
            self.assertFalse((Path(home)/'.config/claude-subagent-proxy/config.json').exists())

    def test_quoted_dotenv_key_file_matches_proxy(self):
        with tempfile.TemporaryDirectory() as home, provider() as (url, calls):
            keyfile = Path(home)/'key.env';keyfile.write_text('CUSTOM_KEY="'+KEY+'"\n')
            check_provider({'base_url':url,'model':'m','auth_type':'bearer','api_key_file':str(keyfile),'api_key_format':'dotenv','api_key_env':'CUSTOM_KEY'})
            self.assertEqual(calls[0]['headers'].get('Authorization'), 'Bearer '+KEY)

    def test_streaming_deadline_is_bounded(self):
        with provider('slow') as (url, _):
            start = time.monotonic()
            with self.assertRaisesRegex(ProviderCheckError, 'timed out'):
                stream_message(self.config(url), {'max_tokens':32,'messages':[]}, timeout=0.15)
            self.assertLess(time.monotonic()-start, 0.5)

    def test_messages_url_normalization(self):
        for base in ('http://localhost:8317', 'http://localhost:8317/v1', 'http://localhost:8317/v1/messages/'):
            self.assertEqual(messages_url(base), 'http://localhost:8317/v1/messages')

    def test_failed_or_unfunded_provider_saves_unverified_by_default(self):
        for mode in ('no-balance', 'no-tool', 'tool400', 'catalog-missing-tool400'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home, provider(mode) as (url, _):
                result = self.cli(home, url)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(KEY, result.stdout+result.stderr)
                self.assertIn('Saving as unverified', result.stdout)
                saved = json.loads((Path(home)/'.config/claude-subagent-proxy/config.json').read_text())
                self.assertEqual(saved['verification']['status'], 'unverified')
                self.assertEqual(saved['verification']['checks']['authentication'], 'passed')
                self.assertEqual(saved['verification']['checks']['model'], 'passed')
                self.assertEqual(saved['subagent']['api_key'], KEY)

    def test_skip_check_only_skips_tool_usage_and_still_checks_auth_model(self):
        with tempfile.TemporaryDirectory() as home, provider() as (url, calls):
            result = self.cli(home, url, '--skip-check')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, [])
            saved = json.loads((Path(home)/'.config/claude-subagent-proxy/config.json').read_text())
            self.assertEqual(saved['verification']['status'], 'partial')
            self.assertEqual(saved['verification']['checks']['tools'], 'skipped')
            self.assertEqual(len(calls.gets), 1)

    def test_environment_variable_references_work_at_hidden_key_prompt(self):
        for reference in ('$SPLIT_TEST_KEY', '${SPLIT_TEST_KEY}', 'env:SPLIT_TEST_KEY'):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as home:
                path = Path(home)/'config.json'
                with patch.object(configuration, 'CONFIG', path), patch.object(configuration.getpass, 'getpass', return_value=reference), patch.object(configuration, 'check_provider', return_value={'authentication':'passed','model':'passed','tools':'skipped'}), patch.dict(os.environ, {'SPLIT_TEST_KEY': KEY}), contextlib.redirect_stdout(io.StringIO()) as output:
                    configuration.configure(['--model', 'worker', '--base-url', 'http://localhost:8317', '--auth', 'bearer', '--skip-check'])
                self.assertEqual(json.loads(path.read_text())['subagent']['api_key'], KEY)
                self.assertNotIn(KEY, output.getvalue())

    def test_missing_or_unsafe_environment_reference_does_not_save(self):
        for reference in ('$SPLIT_TEST_MISSING_KEY', '$(printf unsafe)', '${KEY:-fallback}'):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as home:
                path = Path(home)/'config.json'
                with patch.object(configuration, 'CONFIG', path), patch.object(configuration.getpass, 'getpass', return_value=reference), patch.dict(os.environ, {}, clear=True):
                    with self.assertRaises(ValueError):
                        configuration.configure(['--model', 'worker', '--base-url', 'http://localhost:8317', '--auth', 'bearer', '--skip-check'])
                self.assertFalse(path.exists())

    def test_mandatory_auth_model_and_protocol_failures_never_save_by_default(self):
        for mode in ('unauthorized', 'second-fails', 'bad-model', 'quota-before-catalog', 'catalog-missing-no-balance', 'json', 'malformed', 'redirect'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home, provider(mode) as (url, _):
                path = Path(home)/'.config/claude-subagent-proxy/config.json'
                path.parent.mkdir(parents=True); path.write_text('{"subagent":{"model":"old"}}')
                previous = path.read_bytes()
                result = self.cli(home, url)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(path.read_bytes(), previous)
                self.assertNotIn(KEY, result.stdout+result.stderr)

    def test_skip_tool_option_cannot_bypass_bad_auth_or_unknown_model(self):
        for mode in ('unauthorized', 'bad-model', 'catalog-missing-no-balance'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home, provider(mode) as (url, _):
                result = self.cli(home, url, '--skip-check')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((Path(home)/'.config/claude-subagent-proxy/config.json').exists())

    def test_no_catalog_uses_successful_messages_to_verify_model_and_auth(self):
        with provider('catalog-missing') as (url, calls):
            report = check_provider(self.config(url))
            self.assertEqual(report['model_check'], 'messages_api')
            self.assertEqual(report['authentication'], 'passed')
            self.assertEqual(report['tools'], 'passed')
            self.assertEqual(len(calls), 2)


if __name__ == '__main__': unittest.main(verbosity=2)
