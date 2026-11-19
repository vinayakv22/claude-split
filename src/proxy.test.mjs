import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import { gzipSync } from 'node:zlib';
import { once } from 'node:events';
import { createProxy, validateSubagentConfig } from './proxy.mjs';

async function fixture(t, options = {}) {
  const captured = [];
  const upstream = http.createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    captured.push({ url: req.url, headers: req.headers, body: Buffer.concat(chunks) });
    if (options.handler) return options.handler(req, res);
    res.writeHead(options.status || 200, { 'content-type': 'application/json', 'x-upstream-marker': 'preserved' });
    res.end(JSON.stringify({ ok: true }));
  });
  upstream.listen(0, '127.0.0.1'); await once(upstream, 'listening');
  const url = `http://127.0.0.1:${upstream.address().port}`;
  const proxy = createProxy({ anthropicUrl: url, getConfig: () => ({ base_url: url + '/anthropic', model: 'deepseek-flash' }), getKey: () => 'deepseek-test-key', ...options });
  proxy.listen(0, '127.0.0.1'); await once(proxy, 'listening');
  t.after(() => { proxy.closeAllConnections(); proxy.close(); upstream.closeAllConnections(); upstream.close(); });
  return { captured, proxy, upstream, base: `http://127.0.0.1:${proxy.address().port}` };
}
function request(base, body, headers = {}) {
  return fetch(base + '/v1/messages?beta=true', { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body });
}

test('Claude route preserves exact body bytes, login, device metadata, client identity, and query', async t => {
  const f = await fixture(t);
  const body = '{ "model": "claude-opus-5-5", "metadata": {"user_id":"{\\"device_id\\":\\"original-device\\",\\"account_uuid\\":\\"original-account\\"}"}, "messages": [] }\n';
  const response = await request(f.base, body, { authorization: 'Bearer claude-test-token',
    'user-agent': 'claude-cli/test', 'x-app': 'cli', 'x-claude-code-session-id': 'original-session',
    'x-client-request-id': 'original-request', 'anthropic-beta': 'original-beta' });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('x-upstream-marker'), 'preserved');
  const req = f.captured[0];
  assert.equal(req.body.toString(), body);
  assert.equal(req.headers.authorization, 'Bearer claude-test-token');
  assert.equal(req.headers['x-app'], 'cli');
  assert.equal(req.headers['user-agent'], 'claude-cli/test');
  assert.equal(req.headers['x-claude-code-session-id'], 'original-session');
  assert.equal(req.headers['x-client-request-id'], 'original-request');
  assert.equal(req.headers['anthropic-beta'], 'original-beta');
  assert.equal(req.url, '/v1/messages?beta=true');
  assert.equal(req.headers.host, `127.0.0.1:${f.upstream.address().port}`);
});

test('DeepSeek receives its key and tools, never Claude authentication or identity metadata', async t => {
  const f = await fixture(t);
  const body = { model: 'deepseek-v4-flash', stream: true,
    metadata: { user_id: '{"device_id":"private","account_uuid":"private"}' },
    system: 'system instructions', messages: [{ role: 'user', content: 'hello' }],
    tools: [{ name: 'Read', input_schema: { type: 'object' } }, { type: 'advisor_20260415', name: 'advisor' }] };
  const response = await request(f.base, JSON.stringify(body), { authorization: 'Bearer private-claude-token',
    'x-api-key': 'private-other-key', cookie: 'private-cookie', 'x-app': 'cli',
    'x-claude-code-session-id': 'private-session', 'anthropic-beta': 'private-beta', 'x-device-id': 'private-device' });
  assert.equal(response.status, 200);
  const req = f.captured[0], parsed = JSON.parse(req.body);
  assert.equal(req.url, '/anthropic/v1/messages');
  assert.equal(req.headers['x-api-key'], 'deepseek-test-key');
  for (const name of ['authorization', 'cookie', 'x-app', 'x-claude-code-session-id', 'anthropic-beta', 'x-device-id']) assert.equal(req.headers[name], undefined);
  assert.equal(parsed.metadata, undefined);
  assert.equal(parsed.model, 'deepseek-flash');
  assert.deepEqual(parsed.tools, [body.tools[0]]);
  assert.deepEqual(parsed.messages, body.messages);
  assert.equal(parsed.system, body.system);
});

test('SSE arrives before upstream finishes and tool events are preserved', async t => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const first = 'event: content_block_start\ndata: {"type":"content_block_start","content_block":{"type":"tool_use","id":"call-1","name":"Read","input":{}}}\n\n';
  const last = 'event: message_stop\ndata: {"type":"message_stop"}\n\n';
  const f = await fixture(t, { handler: async (_req, res) => {
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    res.write(first); await gate; res.end(last);
  } });
  t.after(release);
  const response = await request(f.base, JSON.stringify({ model: 'deepseek-flash', stream: true }));
  const reader = response.body.getReader();
  const next = await reader.read();
  assert.equal(new TextDecoder().decode(next.value), first);
  release();
  let rest = ''; for (;;) { const part = await reader.read(); if (part.done) break; rest += new TextDecoder().decode(part.value); }
  assert.equal(rest, last);
});

test('compressed Claude body is inspected but forwarded without reserialization', async t => {
  const f = await fixture(t);
  const bytes = gzipSync('{ "model": "claude-sonnet-5", "messages": [] }');
  assert.equal((await request(f.base, bytes, { 'content-encoding': 'gzip' })).status, 200);
  assert.deepEqual(f.captured[0].body, bytes);
  assert.equal(f.captured[0].headers['content-encoding'], 'gzip');
});

test('provider errors and retry headers are forwarded without automatic retries', async t => {
  const f = await fixture(t, { handler: (_req, res) => { res.writeHead(429, { 'retry-after': '17' }); res.end('rate limited'); } });
  const response = await request(f.base, '{"model":"claude-opus-5-5"}');
  assert.equal(response.status, 429); assert.equal(response.headers.get('retry-after'), '17');
  assert.equal(await response.text(), 'rate limited'); assert.equal(f.captured.length, 1);
});

test('missing DeepSeek key never falls back to Anthropic', async t => {
  const f = await fixture(t, { getKey: () => '' });
  const response = await request(f.base, '{"model":"deepseek-flash"}');
  assert.equal(response.status, 503); assert.equal(f.captured.length, 0);
});

test('browser-originated and malformed requests never reach providers', async t => {
  const f = await fixture(t);
  assert.equal((await request(f.base, '{}', { origin: 'https://example.com' })).status, 403);
  assert.equal((await request(f.base, 'not json')).status, 400);
  assert.equal((await fetch(f.base + '/https://evil.example')).status, 404);
  assert.equal(f.captured.length, 0);
});

test('disconnecting a streaming client closes the upstream request', async t => {
  let closed;
  const disconnected = new Promise(resolve => { closed = resolve; });
  const f = await fixture(t, { handler: (_req, res) => {
    res.writeHead(200, { 'content-type': 'text/event-stream' }); res.write('event: ping\ndata: {}\n\n');
    res.on('close', closed);
  } });
  const abort = new AbortController();
  const response = await fetch(f.base + '/v1/messages', { method: 'POST', body: '{"model":"deepseek-flash","stream":true}', signal: abort.signal });
  await response.body.getReader().read(); abort.abort();
  await Promise.race([disconnected, new Promise((_,reject) => setTimeout(() => reject(new Error('upstream was not cancelled')), 2000).unref())]);
});

test('custom Messages provider supports root, /v1 base, and full Messages URL without double /v1', async t => {
  for (const suffix of ['', '/v1', '/v1/messages', '/custom/v1']) {
    const f = await fixture(t);
    // A separate proxy targets this fixture's fake CLIProxyAPI server.
    const proxy = createProxy({ getConfig: () => ({ base_url: `http://127.0.0.1:${f.upstream.address().port}${suffix}`, model: 'custom-worker-model', auth_type: 'bearer', api_key: 'custom-key' }) });
    proxy.listen(0, '127.0.0.1'); await once(proxy, 'listening');
    t.after(() => { proxy.closeAllConnections(); proxy.close(); });
    const response = await request(`http://127.0.0.1:${proxy.address().port}`, JSON.stringify({ model: 'split-subagent', messages: [] }), { authorization: 'Bearer claude-private', cookie: 'private' });
    assert.equal(response.status, 200);
    const req = f.captured[0];
    assert.equal(req.url, suffix.startsWith('/custom') ? '/custom/v1/messages' : '/v1/messages');
    assert.equal(req.headers.authorization, 'Bearer custom-key');
    assert.equal(req.headers['x-api-key'], undefined);
    assert.equal(req.headers.cookie, undefined);
    assert.equal(JSON.parse(req.body).model, 'custom-worker-model');
  }
});

test('a Claude-named subagent model is distinct from the main Claude route', async t => {
  const f = await fixture(t, { getConfig: () => ({ base_url: `http://127.0.0.1:${f.upstream.address().port}/worker`, model: 'claude-sonnet-5', auth_type: 'x-api-key' }) });
  await request(f.base, '{ "model": "claude-sonnet-5", "messages": [] }', { authorization: 'Bearer main-account' });
  await request(f.base, '{"model":"split-subagent","messages":[]}', { authorization: 'Bearer main-account' });
  assert.equal(f.captured[0].url, '/v1/messages?beta=true');
  assert.equal(f.captured[0].headers.authorization, 'Bearer main-account');
  assert.equal(f.captured[1].url, '/worker/v1/messages');
  assert.equal(f.captured[1].headers.authorization, undefined);
  assert.equal(JSON.parse(f.captured[1].body).model, 'claude-sonnet-5');
});

test('shared configuration can be changed without restarting the proxy', async t => {
  let model = 'first-worker';
  const f = await fixture(t, { getConfig: () => ({ base_url: `http://127.0.0.1:${f.upstream.address().port}/worker`, model }) });
  await request(f.base, '{"model":"split-subagent"}');
  model = 'second-worker';
  await request(f.base, '{"model":"split-subagent"}');
  assert.deepEqual(f.captured.map(r => JSON.parse(r.body).model), ['first-worker', 'second-worker']);
});

test('keyless providers receive no credentials and health never exposes provider keys', async t => {
  const f = await fixture(t, { getConfig: () => ({ base_url: `http://127.0.0.1:${f.upstream.address().port}`, model: 'local-model', auth_type: 'none' }), getKey: () => '' });
  const response = await request(f.base, '{"model":"split-subagent"}', { authorization: 'Bearer claude-private', 'x-api-key': 'private-key' });
  assert.equal(response.status, 200);
  assert.equal(f.captured[0].headers.authorization, undefined);
  assert.equal(f.captured[0].headers['x-api-key'], undefined);
  const health = await (await fetch(f.base+'/healthz')).json();
  assert.equal(health.subagent.ready, true);
  assert.equal(health.subagent.authType, 'none');
  assert.equal(health.subagent.api_key, undefined);
});

test('invalid subagent config does not break the main route or leak configuration', async t => {
  const f = await fixture(t, { getConfig: () => { throw new Error('private-config-key'); } });
  assert.equal((await request(f.base, '{"model":"claude-sonnet-5"}')).status, 200);
  const response = await request(f.base, '{"model":"split-subagent"}');
  assert.equal(response.status, 503);
  assert.doesNotMatch(await response.text(), /private-config-key/);
  assert.doesNotMatch(await (await fetch(f.base+'/healthz')).text(), /private-config-key/);
});

test('old DeepSeek sessions fail explicitly after selecting a different worker model', async t => {
  const f = await fixture(t, { getConfig: () => ({ base_url: `http://127.0.0.1:${f.upstream.address().port}`, model: 'new-model' }) });
  assert.equal((await request(f.base, '{"model":"deepseek-flash"}')).status, 409);
  assert.equal(f.captured.length, 0);
});

test('configuration rejects unsafe URLs, proxy loops and invalid auth', () => {
  for (const config of [
    { base_url: 'file:///tmp/a', model: 'm' },
    { base_url: 'http://user:password@localhost:8000', model: 'm' },
    { base_url: 'https://example.com?key=private', model: 'm' },
    { base_url: 'http://127.0.0.1:3457', model: 'm' },
    { base_url: 'http://localhost:8000', model: 'split-subagent' },
    { base_url: 'https://example.com', model: 'm', auth_type: 'cookie' },
  ]) assert.throws(() => validateSubagentConfig(config));
});

test('inline tool definitions are hoisted and additions become references for subagents', async t => {
  const f = await fixture(t);
  const definition = { name: 'Read', description: 'Read a file', input_schema: { type: 'object', properties: { path: { type: 'string' } } } };
  const payload = { model: 'split-subagent', tool_choice: { type: 'tool', name: 'Read' },
    messages: [{ role: 'user', content: 'Read the file' }, { role: 'system', content: [
      { type: 'tool_addition', tool: { type: 'tool_definition', definition }, cache_control: { type: 'ephemeral' } },
      { type: 'text', text: 'Instructions stay intact' },
    ] }] };
  assert.equal((await request(f.base, gzipSync(JSON.stringify(payload)), { 'content-encoding': 'gzip' })).status, 200);
  const sent = JSON.parse(f.captured[0].body);
  assert.deepEqual(sent.tools, [definition]);
  assert.deepEqual(sent.messages[1].content[0], { type: 'tool_addition', tool: { type: 'tool_reference', name: 'Read' }, cache_control: { type: 'ephemeral' } });
  assert.deepEqual(sent.messages[1].content[1], payload.messages[1].content[1]);
  assert.deepEqual(sent.tool_choice, payload.tool_choice);
});

test('inline normalization preserves tool inputs, results, removals, and explicit schema precedence', async t => {
  const f = await fixture(t);
  const old = { name: 'Read', input_schema: { type: 'object' } };
  const current = { ...old, description: 'Current schema', input_schema: { type: 'object', required: ['path'] } };
  const history = { type: 'tool_addition', tool: { type: 'tool_definition', definition: old } };
  const opaqueInput = { type: 'tool_addition', tool: { type: 'tool_definition', definition: { name: 'NotATool' } } };
  const removal = { type: 'tool_removal', tool: { type: 'tool_reference', name: 'Read' } };
  const payload = { model: 'split-subagent', tools: [current], messages: [
    { role: 'system', content: [history, history, removal] },
    { role: 'assistant', content: [{ type: 'tool_use', id: 'call1', name: 'Read', input: opaqueInput }] },
    { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'call1', content: [{ type: 'text', text: 'Original output' }] }] },
  ] };
  assert.equal((await request(f.base, JSON.stringify(payload))).status, 200);
  const sent = JSON.parse(f.captured[0].body);
  assert.deepEqual(sent.tools, [current]);
  assert.deepEqual(sent.messages[0].content[2], removal);
  assert.deepEqual(sent.messages.slice(1), payload.messages.slice(1));
});

test('invalid inline schemas fail locally without forwarding or leaking their contents', async t => {
  const f = await fixture(t);
  const response = await request(f.base, JSON.stringify({ model: 'split-subagent', messages: [
    { role: 'system', content: [{ type: 'tool_addition', tool: { type: 'tool_definition', definition: { name: 'private-marker' } } }] },
  ] }));
  assert.equal(response.status, 400);
  assert.doesNotMatch(await response.text(), /private-marker/);
  assert.equal(f.captured.length, 0);
});

test('main Claude inline definitions still pass through with exact body bytes', async t => {
  const f = await fixture(t);
  const body = '{ "model":"claude-sonnet-5", "messages":[{"role":"system","content":[{"type":"tool_addition","tool":{"type":"tool_definition","definition":{"name":"Read","input_schema":{"type":"object"}}}}]}] }\n';
  assert.equal((await request(f.base, body)).status, 200);
  assert.equal(f.captured[0].body.toString(), body);
});

test('subagent tool schemas normalize null escapes without changing literal backslashes or data', async t => {
  const f = await fixture(t);
  const pattern = '^[^\\0]*$';
  const literal = '^\\\\0$';
  const schema = { type: 'object', properties: {
    path: { type: 'string', pattern },
    pattern: { type: 'string', default: pattern },
    literal: { type: 'string', pattern: literal },
  }, $defs: { nested: { anyOf: [{ type: 'string', pattern }, { type: 'null' }] } },
  patternProperties: { [pattern]: { type: 'string', pattern } },
  examples: [{ pattern }], const: { pattern }, enum: [{ pattern }],
  required: ['path'], additionalProperties: false };
  const body = { model: 'split-subagent', tools: [{ name: 'Artifact', input_schema: schema }],
    messages: [{ role: 'assistant', content: [{ type: 'tool_use', id: 'call', name: 'Artifact', input: { pattern } }] }] };
  assert.equal((await request(f.base, JSON.stringify(body))).status, 200);
  const sent = JSON.parse(f.captured[0].body);
  const expected = '^[^\\x00]*$';
  const normalized = sent.tools[0].input_schema;
  assert.equal(normalized.properties.path.pattern, expected);
  assert.equal(normalized.$defs.nested.anyOf[0].pattern, expected);
  assert.equal(normalized.patternProperties[expected].pattern, expected);
  assert.deepEqual(normalized.properties.literal, schema.properties.literal);
  assert.deepEqual(normalized.properties.pattern, schema.properties.pattern);
  assert.deepEqual(normalized.examples, schema.examples);
  assert.deepEqual(normalized.const, schema.const);
  assert.deepEqual(normalized.enum, schema.enum);
  assert.deepEqual(normalized.required, ['path']);
  assert.equal(normalized.additionalProperties, false);
  assert.deepEqual(sent.messages, body.messages);
  for (const value of ['', 'abc', 'a\nb', 'abc\0def', '\0', '\\0', '😀']) {
    assert.equal(new RegExp(pattern, 'u').test(value), new RegExp(expected, 'u').test(value));
  }
});

test('inline schemas get portable regexes, while main requests stay byte-identical', async t => {
  const f = await fixture(t);
  const definition = { name: 'Artifact', input_schema: { type: 'string', pattern: '^[^\\0]*$' } };
  const body = { model: 'split-subagent', messages: [{ role: 'system', content: [
    { type: 'tool_addition', tool: { type: 'tool_definition', definition } },
  ] }] };
  assert.equal((await request(f.base, JSON.stringify(body))).status, 200);
  assert.equal(JSON.parse(f.captured[0].body).tools[0].input_schema.pattern, '^[^\\x00]*$');
  const main = JSON.stringify({ ...body, model: 'claude-sonnet-5', tools: [definition] }) + '\n';
  assert.equal((await request(f.base, main)).status, 200);
  assert.equal(f.captured[1].body.toString(), main);
});

test('portable null escaping distinguishes escaped backslashes and octal sequences', async () => {
  const { portablePattern } = await import('./proxy.mjs');
  for (const [input, expected] of [
    ['\\0', '\\x00'], ['\\\\0', '\\\\0'], ['\\\\\\0', '\\\\\\x00'],
    ['\\01', '\\01'], ['\\00', '\\00'], ['\\x00', '\\x00'], ['\\u0000', '\\u0000'], ['abc\\', 'abc\\'],
  ]) assert.equal(portablePattern(input), expected);
});
