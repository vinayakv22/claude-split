"""Bounded live Anthropic Messages streaming and tool-round-trip check."""
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, urlencode


class ProviderCheckError(Exception):
    pass


class ProviderHTTPError(ProviderCheckError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class ToolCheckError(ProviderCheckError):
    """Only raised after authentication and model verification succeeded."""
    def __init__(self, message, checks):
        self.checks = {**checks, 'tools': 'unverified'}
        super().__init__(message)


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def messages_url(base_url):
    parts = urlsplit(base_url)
    path = parts.path.rstrip('/')
    if path.endswith('/v1/messages'):
        pass
    elif path.endswith('/v1'):
        path += '/messages'
    else:
        path += '/v1/messages'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


def read_key(config):
    if config.get('auth_type', 'x-api-key') == 'none':
        return ''
    if config.get('api_key'):
        key = str(config['api_key']).strip()
    else:
        try:
            text = Path(config['api_key_file']).expanduser().read_text()
        except (OSError, KeyError, ValueError):
            raise ProviderCheckError('Cannot read the configured API key file.') from None
        if config.get('api_key_format') == 'dotenv':
            prefix = config.get('api_key_env', 'SUBAGENT_API_KEY') + '='
            key = next((line[len(prefix):].strip() for line in text.splitlines() if line.startswith(prefix)), '')
            if len(key) >= 2 and key[0] == key[-1] and key[0] in ('"', "'"):
                key = key[1:-1]
        else:
            key = text.strip()
    if not key or any(ord(c) < 32 or ord(c) > 126 for c in key):
        raise ProviderCheckError('API key is missing or contains invalid characters.')
    return key


def stream_message(config, payload, *, timeout=20):
    headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream',
               'Anthropic-Version': '2023-06-01'}
    auth = config.get('auth_type', 'x-api-key')
    key = read_key(config)
    if auth == 'x-api-key':
        headers['X-Api-Key'] = key
    elif auth == 'bearer':
        headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(messages_url(config['base_url']),
        data=json.dumps({**payload, 'model': config['model'], 'stream': True}).encode(), headers=headers)
    opener = urllib.request.build_opener(NoRedirects())
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ProviderCheckError(f'Provider returned HTTP {response.status}.')
            if response.headers.get_content_type() != 'text/event-stream':
                raise ProviderCheckError('Endpoint did not return Anthropic SSE streaming; verify the Messages API URL.')
            started = stopped = False
            blocks = {}
            data_lines = []
            total = 0
            stop_reason = None

            def consume():
                nonlocal started, stopped, stop_reason
                if not data_lines:
                    return
                try:
                    event = json.loads('\n'.join(data_lines))
                except (ValueError, TypeError):
                    raise ProviderCheckError('Provider returned malformed SSE JSON.') from None
                data_lines.clear()
                if not isinstance(event, dict):
                    raise ProviderCheckError('Provider returned an invalid Anthropic event.')
                kind = event.get('type')
                if kind == 'error':
                    raise ProviderCheckError('Provider reported an error during streaming.')
                if kind == 'message_start':
                    if event.get('message', {}).get('type') != 'message':
                        raise ProviderCheckError('Invalid Anthropic message_start event.')
                    started = True
                elif kind == 'content_block_start':
                    block = event.get('content_block')
                    if not isinstance(block, dict):
                        raise ProviderCheckError('Invalid Anthropic content block.')
                    blocks[event.get('index')] = {**block, '_json': ''}
                elif kind == 'content_block_delta':
                    block = blocks.get(event.get('index'))
                    delta = event.get('delta', {})
                    if not isinstance(delta, dict) or block is None:
                        raise ProviderCheckError('Invalid Anthropic content delta.')
                    if delta.get('type') == 'input_json_delta':
                        block['_json'] += delta.get('partial_json', '')
                    elif delta.get('type') == 'text_delta':
                        block['text'] = block.get('text', '') + delta.get('text', '')
                elif kind == 'message_delta':
                    stop_reason = event.get('delta', {}).get('stop_reason')
                elif kind == 'message_stop':
                    stopped = True

            while not stopped:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderCheckError('Provider streaming check timed out.')
                # Limit each blocking read to the remaining wall-clock deadline.
                try:
                    response.fp.raw._sock.settimeout(remaining)
                except AttributeError:
                    pass
                line = response.readline(65537)
                if not line:
                    consume()
                    break
                total += len(line)
                if len(line) > 65536 or total > 1024 * 1024:
                    raise ProviderCheckError('Provider check response exceeded its size limit.')
                try:
                    text = line.decode('utf-8').rstrip('\r\n')
                except UnicodeError:
                    raise ProviderCheckError('Provider returned invalid SSE text.') from None
                if not text:
                    consume()
                elif text.startswith('data:'):
                    data_lines.append(text[5:].lstrip(' '))
            if not started or not stopped:
                raise ProviderCheckError('Provider did not complete an Anthropic SSE message.')
            content = []
            for block in blocks.values():
                partial = block.pop('_json')
                if partial:
                    try:
                        block['input'] = json.loads(partial)
                    except ValueError:
                        raise ProviderCheckError('Provider returned invalid tool-call JSON.') from None
                content.append(block)
            return content, stop_reason
    except urllib.error.HTTPError as error:
        error.close()
        descriptions = {400: 'Model or Messages/tool configuration was rejected.',
            401: 'API key was rejected.', 402: 'Provider billing or credit balance prevented verification.', 403: 'Access to this model or endpoint was denied.',
            404: 'Messages endpoint or model was not found.', 429: 'Provider rate limit or quota prevented verification.'}
        detail = descriptions.get(error.code, 'Provider request failed.')
        if 300 <= error.code < 400:
            detail = 'Redirect was not followed; configure the final API endpoint.'
        # Do not echo upstream error bodies: they can contain reflected credentials.
        raise ProviderHTTPError(error.code, f'HTTP {error.code}: {detail}') from None
    except (TimeoutError, socket.timeout):
        raise ProviderCheckError('Provider connection or streaming check timed out.') from None
    except (urllib.error.URLError, OSError):
        raise ProviderCheckError('Cannot reach the provider; check its address, network, and TLS certificate.') from None
    except (ValueError, TypeError, AttributeError, KeyError):
        raise ProviderCheckError('Provider returned an invalid Anthropic Messages response.') from None


def check_tool_round_trip(config, *, timeout=20, checks=None):
    tool_name = 'split_connection_check'
    tool = {'name': tool_name, 'description': 'Return a fixed test value.',
            'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}
    messages = [{'role': 'user', 'content': f'Call {tool_name} exactly once with empty input. After its result, reply with the result only.'}]
    base = {'max_tokens': 128, 'thinking': {'type': 'disabled'}, 'tools': [tool]}
    verified = dict(checks or {})
    try:
        content, reason = stream_message(config, {**base, 'messages': messages,
            'tool_choice': {'type': 'tool', 'name': tool_name}}, timeout=timeout)
    except ProviderHTTPError as error:
        if verified and error.status in (400, 402, 429):
            raise ToolCheckError(str(error), verified) from None
        raise
    # A complete Messages response proves the credentials/model request was accepted.
    verified = {'authentication': 'not_required' if config.get('auth_type') == 'none' else 'passed',
                'model': 'passed', 'model_check': verified.get('model_check', 'messages_api')}
    uses = [block for block in content if block.get('type') == 'tool_use']
    if len(uses) != 1 or uses[0].get('name') != tool_name or not uses[0].get('id') or uses[0].get('input') != {} or reason != 'tool_use':
        raise ToolCheckError('Authentication/model passed, but the model did not return the required compatible tool call.', verified)
    messages.extend([{'role': 'assistant', 'content': content}, {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': uses[0]['id'], 'content': 'SPLIT_CHECK_OK'}]}])
    try:
        content, reason = stream_message(config, {**base, 'max_tokens': 32, 'messages': messages,
            'tool_choice': {'type': 'none'}}, timeout=timeout)
    except ProviderHTTPError as error:
        if error.status in (400, 402, 429):
            raise ToolCheckError(str(error), verified) from None
        raise
    if reason != 'end_turn' or not any(block.get('type') == 'text' and block.get('text', '').strip() for block in content):
        raise ToolCheckError('The provider did not complete the tool-result round trip with a text reply.', verified)
    return {**verified, 'tools': 'passed'}


def verify_catalog(config, *, timeout=20):
    """Use an authenticated model listing where supported, with no inference usage."""
    headers = {'Accept': 'application/json', 'Anthropic-Version': '2023-06-01'}
    auth = config.get('auth_type', 'x-api-key')
    key = read_key(config)
    if auth == 'x-api-key': headers['X-Api-Key'] = key
    elif auth == 'bearer': headers['Authorization'] = 'Bearer ' + key
    endpoint = messages_url(config['base_url']).rsplit('/', 1)[0] + '/models'
    opener = urllib.request.build_opener(NoRedirects())
    deadline = time.monotonic() + timeout
    after = None
    for _ in range(10):
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise ProviderCheckError('Model verification timed out.')
        url = endpoint + ('?' + urlencode({'after_id': after}) if after else '')
        request = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(request, timeout=remaining) as response:
                if response.status != 200: raise ProviderCheckError('Model-list endpoint did not return HTTP 200.')
                payload = response.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024: raise ProviderCheckError('Model listing exceeded its size limit.')
                data = json.loads(payload)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code in (404, 405, 501) and after is None:
                return None  # Gateway has no model listing: verify through Messages instead.
            details = {401: 'API key was rejected.', 403: 'Access was denied.',
                       402: 'Insufficient balance prevented authentication/model verification.',
                       429: 'Quota or rate limiting prevented authentication/model verification.'}
            raise ProviderHTTPError(error.code, f'HTTP {error.code}: ' + details.get(error.code, 'Model verification failed.')) from None
        except (TimeoutError, socket.timeout):
            raise ProviderCheckError('Model verification timed out.') from None
        except (urllib.error.URLError, OSError):
            raise ProviderCheckError('Cannot reach the provider for authentication/model verification.') from None
        except (ValueError, TypeError):
            raise ProviderCheckError('Model-list endpoint returned invalid JSON.') from None
        if not isinstance(data, dict) or not isinstance(data.get('data'), list):
            raise ProviderCheckError('Model-list endpoint returned an invalid model listing.')
        ids = [entry.get('id') for entry in data['data'] if isinstance(entry, dict)]
        if config['model'] in ids:
            return {'authentication': 'not_required' if auth == 'none' else 'passed', 'model': 'passed', 'model_check': 'models_api'}
        if not data.get('has_more'):
            raise ProviderCheckError('Configured model was not found in the authenticated provider model listing.')
        next_id = data.get('last_id') or (ids[-1] if ids else None)
        if not isinstance(next_id, str) or not next_id or next_id == after:
            raise ProviderCheckError('Provider model-list pagination could not be verified.')
        after = next_id
    raise ProviderCheckError('Model verification exceeded the model-list pagination limit.')


def verify_simple_message(config, *, timeout):
    content, _ = stream_message(config, {'max_tokens': 16, 'thinking': {'type': 'disabled'},
        'messages': [{'role': 'user', 'content': 'Reply OK.'}]}, timeout=timeout)
    if not any(block.get('type') == 'text' and block.get('text', '').strip() for block in content):
        raise ProviderCheckError('Authentication/model verification did not produce a text reply.')
    return {'authentication': 'not_required' if config.get('auth_type') == 'none' else 'passed',
            'model': 'passed', 'model_check': 'messages_api'}


def check_provider(config, *, timeout=20, skip_tools=False):
    checks = verify_catalog(config, timeout=timeout)
    if not skip_tools:
        try:
            return check_tool_round_trip(config, timeout=timeout, checks=checks)
        except ProviderHTTPError as error:
            # A tool payload rejection is not proof that the key/model works.
            # Isolate it with a tiny tool-free request when no model API exists.
            if checks is None and error.status == 400:
                checks = verify_simple_message(config, timeout=timeout)
                raise ToolCheckError('Model accepted a tool-free request, but rejected the tool request (HTTP 400).', checks) from None
            raise
    if checks is None:
        checks = verify_simple_message(config, timeout=timeout)
    return {**checks, 'tools': 'skipped'}
