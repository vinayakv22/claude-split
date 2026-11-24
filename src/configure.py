#!/usr/bin/env python3
"""Configure the shared Anthropic-compatible subagent upstream."""
import argparse
import getpass
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit
from provider_check import check_provider, list_models, ProviderCheckError, ToolCheckError

CONFIG = Path.home()/'.config/claude-subagent-proxy/config.json'
# Starting points only: every choice is verified live before it is saved.
PROVIDERS = {
    'deepseek': ('DeepSeek', 'https://api.deepseek.com/anthropic', 'x-api-key'),
    'anthropic': ('Anthropic API (separate API key)', 'https://api.anthropic.com', 'x-api-key'),
    'moonshot': ('Moonshot AI / Kimi', 'https://api.moonshot.ai/anthropic', 'bearer'),
    'zai': ('Z.ai / GLM', 'https://api.z.ai/api/anthropic', 'bearer'),
    'minimax': ('MiniMax', 'https://api.minimax.io/anthropic', 'bearer'),
    'openrouter': ('OpenRouter', 'https://openrouter.ai/api', 'bearer'),
    'local': ('Local gateway (CLIProxyAPI or similar)', 'http://127.0.0.1:8317/v1', 'bearer'),
}

def resolve_key_input(value):
    """Expand a whole environment-variable reference without invoking a shell."""
    match = re.fullmatch(r'(?:\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}|env:([A-Za-z_][A-Za-z0-9_]*))', value)
    if match:
        name = next(group for group in match.groups() if group)
        key = os.environ.get(name, '').strip()
        if not key:
            raise ValueError(f'Environment variable {name} is unset or empty; export it in this terminal.')
        return key
    if value.startswith(('$', 'env:')):
        raise ValueError('Use $NAME, ${NAME}, or env:NAME for an exported environment variable.')
    return value


def ask(label, value=''):
    return input(f'{label}' + (f' [{value}]' if value else '') + ': ').strip() or value


def choose_provider(current):
    options = [*PROVIDERS, 'custom']
    base = current.get('base_url', '').rstrip('/')
    default = next((n for n in PROVIDERS if PROVIDERS[n][1] == base), 'custom' if base else 'deepseek')
    print('Subagent provider (any Anthropic Messages-compatible endpoint):')
    for number, name in enumerate(options, 1):
        print(f'  {number}) {name:<11} {PROVIDERS[name][0] if name in PROVIDERS else "Custom URL"}')
    while True:
        answer = ask('Choose a number or name', default)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        if answer in options:
            return answer
        print('Enter one of the listed numbers or names.')


def choose_model(config, current_model):
    print('Fetching the provider model list...', flush=True)
    models = list_models(config) or []
    shown = models[:40]
    for number, name in enumerate(shown, 1):
        print(f'  {number}) {name}')
    if len(models) > len(shown):
        print(f'  ... and {len(models) - len(shown)} more (type any model ID)')
    if not models:
        print('No model list available; enter the model ID from your provider documentation.')
    default = current_model if current_model and (not models or current_model in models) else (shown[0] if shown else '')
    while True:
        answer = ask('Subagent model (number or ID)', default)
        if shown and answer.isdigit() and 1 <= int(answer) <= len(shown):
            return shown[int(answer) - 1]
        if answer:
            return answer


def configure(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=sorted(PROVIDERS), help='Preset base URL and authentication (override with --base-url/--auth)')
    parser.add_argument('--model', help='Upstream subagent model ID')
    parser.add_argument('--base-url', help='Anthropic Messages API root, /v1 base, or /v1/messages URL')
    parser.add_argument('--auth', choices=['x-api-key', 'bearer', 'none'])
    parser.add_argument('--key-file', help='Private file containing the upstream API key')
    parser.add_argument('--key-env', help='Read this entry from a dotenv key file instead of treating it as plain text')
    parser.add_argument('--api-key-stdin', action='store_true', help='Read the API key from standard input instead of prompting')
    parser.add_argument('--api-key-env', metavar='NAME', help='Read the API key from this exported environment variable')
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument('--skip-check', action='store_true', help='Skip tool/usage testing; authentication and model verification are still required')
    checks.add_argument('--require-check', action='store_true', help='Require successful live verification before saving')
    args = parser.parse_args(argv)
    if sum(map(bool, (args.key_file, args.api_key_stdin, args.api_key_env))) > 1:
        parser.error('Choose one of --key-file, --api-key-stdin, or --api-key-env')
    if args.key_env and not args.key_file:
        parser.error('--key-env requires --key-file')
    try:
        current = json.loads(CONFIG.read_text()).get('subagent', {})
    except (OSError, ValueError):
        current = {}
    preset = PROVIDERS.get(args.provider)
    url = args.base_url or (preset[1] if preset else None)
    auth = args.auth or (preset[2] if preset else None)
    if url is None and args.model is None:
        name = choose_provider(current)
        if name == 'custom':
            url = ask('Anthropic-compatible base URL', current.get('base_url', ''))
            auth = auth or ask('Authentication: x-api-key, bearer, none', current.get('auth_type', 'x-api-key'))
        else:
            url, auth = PROVIDERS[name][1], auth or PROVIDERS[name][2]
    elif url is None:
        url = ask('Anthropic-compatible base URL', current.get('base_url', ''))
    auth = auth or current.get('auth_type', 'x-api-key')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('Use an http(s) API URL without credentials, query parameters, or fragments')
    if parsed.hostname in ('localhost', '127.0.0.1', '::1') and parsed.port == 3457:
        parser.error('The upstream cannot be the local split proxy itself')
    if auth not in ('x-api-key', 'bearer', 'none'):
        parser.error('Invalid authentication type')
    config = {'model': '', 'base_url': url.rstrip('/'), 'auth_type': auth}
    if auth != 'none':
        if args.key_file:
            key_file = Path(args.key_file).expanduser().resolve()
            if not key_file.is_file(): parser.error('The key file must exist')
            config.update(api_key_file=str(key_file), api_key_format='dotenv' if args.key_env else 'plain')
            if args.key_env: config['api_key_env'] = args.key_env
        else:
            reuse = current.get('base_url', '').rstrip('/') == config['base_url'] and any(current.get(k) for k in ('api_key', 'api_key_file'))
            if args.api_key_env:
                key = 'env:' + args.api_key_env
            elif args.api_key_stdin:
                key = sys.stdin.readline().strip()
            else:
                key = ''
                while not key:
                    key = getpass.getpass('API key (or $ENV_VAR)' + (' (Enter keeps existing key)' if reuse else '') + ': ').strip()
                    if reuse or key: break
                    print('An API key is required for this provider (Ctrl-C to cancel).')
            if key:
                key = resolve_key_input(key)
                if '\n' in key or '\r' in key: parser.error('Invalid API key')
                config['api_key'] = key
            elif reuse and not (args.api_key_stdin or args.api_key_env):
                for key in ('api_key', 'api_key_file', 'api_key_format', 'api_key_env'):
                    if key in current: config[key] = current[key]
            else:
                parser.error('An API key is required for this endpoint')
    if args.model is None:
        same = current.get('base_url', '').rstrip('/') == config['base_url']
        model = choose_model(config, current.get('model') if same else '')
    else:
        model = args.model
    if not model.strip() or model.strip() == 'split-subagent':
        parser.error('Invalid upstream model')
    config['model'] = model.strip()
    print('Verifying provider authentication and model' + (' (tool test skipped)...' if args.skip_check else ', then streaming/tool support...'), flush=True)
    try:
        checks = check_provider(config, skip_tools=args.skip_check)
    except ToolCheckError as error:
        if args.require_check:
            raise
        verification = {'status': 'unverified', 'checked_at': datetime.now(timezone.utc).isoformat(),
                        'checks': error.checks, 'reason': str(error)}
        print('Authentication and model verification passed.', flush=True)
        print(f'Tool/usage verification did not pass: {error}', flush=True)
        print('Saving as unverified; the tool/usage check can be retried after funding or fixing tool support.', flush=True)
    else:
        verification = {'status': 'partial' if args.skip_check else 'passed',
                        'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks}
        print('Authentication/model verified; tool test skipped.' if args.skip_check else 'Provider verification passed.', flush=True)
    CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=CONFIG.parent, prefix='.config-', delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps({'subagent': config, 'verification': verification}, indent=2)+'\n')
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(CONFIG)
    print(f'Saved subagent: {config["model"]} at {config["base_url"]}')
    print(f'Private configuration: {CONFIG}')
    print('Applies to all requests through this shared proxy. Start a new claude-split session.')

if __name__ == '__main__':
    try:
        configure(sys.argv[1:])
    except (ProviderCheckError, OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        sys.exit(f'Configuration not saved: {error}')
