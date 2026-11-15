import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { homedir } from 'node:os';
import { createProxy } from './proxy.mjs';

// Real RTK binary, isolated loopback providers; no billable requests.
test('RTK compresses both split routes, preserves credentials, model selection and SSE', { timeout: 20000 }, async t => {
  const captured = [];
  const upstream = http.createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks));
    captured.push({ headers: req.headers, body });
    const message = { id: 'msg_mock', type: 'message', role: 'assistant', model: body.model,
      content: [{ type: 'text', text: 'OK' }], stop_reason: 'end_turn', stop_sequence: null,
      usage: { input_tokens: 20, output_tokens: 1 } };
    if (body.stream) {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write(`event: message_start\ndata: ${JSON.stringify({ type: 'message_start', message: { ...message, content: [], stop_reason: null } })}\n\n`);
      res.write('event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n');
      res.write('event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"OK"}}\n\n');
      res.write('event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n');
      res.write('event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":1}}\n\n');
      res.end('event: message_stop\ndata: {"type":"message_stop"}\n\n');
    } else { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(message)); }
  });
  const servers = [upstream];
  let child;
  t.after(() => { child?.kill(); for (const server of servers) { server.closeAllConnections(); server.close(); } });
  upstream.listen(0, '127.0.0.1'); await once(upstream, 'listening');
  const upstreamUrl = `http://127.0.0.1:${upstream.address().port}`;
  const split = createProxy({ anthropicUrl: upstreamUrl,
    getConfig: () => ({ base_url: upstreamUrl, model: 'mock-worker' }), getKey: () => 'mock-provider-key' });
  servers.push(split); split.listen(0, '127.0.0.1'); await once(split, 'listening');
  const reserve = http.createServer(); reserve.listen(0, '127.0.0.1'); await once(reserve, 'listening');
  const port = reserve.address().port; await new Promise(resolve => reserve.close(resolve));
  const base = `http://127.0.0.1:${port}`;
  child = spawn(`${homedir()}/.local/bin/rtk-proxy`, ['start', '--bind', `127.0.0.1:${port}`,
    '--anthropic-upstream', `http://127.0.0.1:${split.address().port}`, '--db', 'off',
    '--ccr', 'false', '--relay-borrowing', 'false', '--cache-align', 'false', '--normalize', 'true'],
    { stdio: ['ignore', 'ignore', 'pipe'] });
  let log = ''; child.stderr.on('data', chunk => { log += chunk; });
  for (let n = 0; ; n++) {
    try { const response = await fetch(base + '/health'); if (response.ok) break; } catch {}
    if (child.exitCode !== null || n > 100) throw Error(`RTK startup failed: ${log}`);
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  for (const stream of [false, true]) for (const model of ['claude-test-model', 'split-subagent']) {
    const response = await fetch(base + '/v1/messages?beta=true', { method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer mock-claude-login',
        'anthropic-version': '2023-06-01', 'anthropic-beta': 'mock-beta', 'x-app': 'cli',
        'x-claude-code-session-id': 'mock-session', 'user-agent': 'claude-cli/mock' },
      body: JSON.stringify({ model, max_tokens: 32, stream, metadata: { user_id: 'mock-device-account' },
        messages: [{ role: 'user', content: 'Run the command' },
          { role: 'assistant', content: [{ type: 'tool_use', id: 'tool_mock', name: 'Bash', input: { command: 'printf OK' } }] },
          { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'tool_mock', content: '\u001b[32mOK\u001b[0m\n'.repeat(100) }] }],
        tools: [{ name: 'Bash', input_schema: { type: 'object', properties: { command: { type: 'string' } } } }] }) });
    assert.equal(response.status, 200);
    const output = await response.text();
    if (stream) { assert.match(output, /text_delta/); assert.match(output, /message_stop/); }
    else assert.equal(JSON.parse(output).content[0].text, 'OK');
    const req = captured.at(-1);
    assert.equal(req.body.messages[2].content[0].tool_use_id, 'tool_mock');
    assert.doesNotMatch(req.body.messages[2].content[0].content, /\u001b/);
    assert.match(req.body.messages[2].content[0].content, /OK/);
    if (model === 'split-subagent') {
      assert.equal(req.body.model, 'mock-worker');
      assert.equal(req.headers['x-api-key'], 'mock-provider-key');
      assert.equal(req.headers.authorization, undefined);
      assert.equal(req.body.metadata, undefined);
    } else {
      assert.equal(req.body.model, model);
      assert.equal(req.headers.authorization, 'Bearer mock-claude-login');
      assert.equal(req.headers['anthropic-beta'], 'mock-beta');
      assert.equal(req.headers['x-app'], 'cli');
      assert.equal(req.headers['x-claude-code-session-id'], 'mock-session');
      assert.equal(req.headers['user-agent'], 'claude-cli/mock');
      assert.deepEqual(req.body.metadata, { user_id: 'mock-device-account' });
    }
  }
  assert.equal(captured.length, 4);
});
