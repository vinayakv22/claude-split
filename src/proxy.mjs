import http from 'node:http';
import https from 'node:https';
import { readFileSync } from 'node:fs';
import { gunzipSync, inflateSync, brotliDecompressSync } from 'node:zlib';
import { pathToFileURL } from 'node:url';
import { homedir } from 'node:os';

const hopHeaders = new Set(['host', 'connection', 'keep-alive', 'proxy-authenticate',
  'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade']);
export const subagentAlias = 'split-subagent';
const legacyModels = ['deepseek-flash', 'deepseek-v4-flash'];
const defaultConfigPath = `${homedir()}/.config/claude-subagent-proxy/config.json`;
const maxBody = 64 * 1024 * 1024;

function errorResponse(res, status, message) {
  if (res.headersSent) { res.destroy(); return; }
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
  res.end(JSON.stringify({ type: 'error', error: { type: 'api_error', message } }));
}
const processSessionId = (await import('node:crypto')).randomUUID();
function rawForwardHeaders(raw, omit = new Set()) {
  const denied = new Set([...hopHeaders, ...omit]);
  for (let i = 0; i < raw.length; i += 2) {
    if (raw[i].toLowerCase() === 'connection') {
      for (const name of raw[i + 1].split(',')) denied.add(name.trim().toLowerCase());
    }
  }
  const result = [];
  for (let i = 0; i < raw.length; i += 2) {
    if (!denied.has(raw[i].toLowerCase())) result.push(raw[i], raw[i + 1]);
  }
  return result;
}
export function loadSubagentConfig(path = defaultConfigPath) {
  return validateSubagentConfig(JSON.parse(readFileSync(path, 'utf8')).subagent);
}
export function validateSubagentConfig(value) {
  if (!value || typeof value !== 'object') throw new Error('Missing subagent configuration');
  const config = { ...value };
  if (typeof config.model !== 'string' || !config.model.trim() || config.model === subagentAlias) throw new Error('Invalid upstream model');
  config.model = config.model.trim();
  const url = new URL(config.base_url);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Invalid base URL');
  if (['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) && url.port === '3457') throw new Error('Upstream cannot be this proxy');
  config.base_url = url.href.replace(/\/$/, '');
  config.auth_type ||= 'x-api-key';
  if (!['x-api-key', 'bearer', 'none'].includes(config.auth_type)) throw new Error('Invalid auth type');
  if (config.api_key_format && !['plain', 'dotenv'].includes(config.api_key_format)) throw new Error('Invalid key-file format');
  return config;
}
function readKey(config) {
  if (config.auth_type === 'none') return '';
  if (config.api_key) return String(config.api_key).trim();
  try {
    const path = config.api_key_file?.replace(/^~(?=\/)/, homedir());
    const text = readFileSync(path, 'utf8');
    if (config.api_key_format !== 'dotenv') return text.trim();
    const prefix = `${config.api_key_env || 'SUBAGENT_API_KEY'}=`;
    let key = text.split(/\r?\n/).find(line => line.startsWith(prefix))?.slice(prefix.length).trim() || '';
    if ((key.startsWith('"') && key.endsWith('"')) || (key.startsWith("'") && key.endsWith("'"))) key = key.slice(1, -1);
    return key;
  } catch { return ''; }
}
function providerUrl(baseUrl, requestPath) {
  const url = new URL(baseUrl);
  let basePath = url.pathname.replace(/\/+$/, '');
  // Accept API roots, /v1 bases, and a full /v1/messages endpoint.
  basePath = basePath.replace(/\/v1\/messages$/, '/v1');
  const path = requestPath.split('?')[0];
  url.pathname = basePath.endsWith('/v1') ? basePath + path.slice(3) : basePath + path;
  url.search = '';
  return url;
}
function decodeJson(raw, encoding) {
  let body = raw;
  if (encoding === 'gzip') body = gunzipSync(raw, { maxOutputLength: maxBody });
  else if (encoding === 'deflate') body = inflateSync(raw, { maxOutputLength: maxBody });
  else if (encoding === 'br') body = brotliDecompressSync(raw, { maxOutputLength: maxBody });
  else if (encoding && encoding !== 'identity') throw new Error('Unsupported content encoding');
  return JSON.parse(body.toString('utf8'));
}
// DeepSeek's schema validator rejects the JavaScript null escape \0.
// \x00 has the same meaning and works across ECMAScript and Rust regex engines.
// Consume escapes in pairs so a literal backslash followed by 0 stays literal.
export function portablePattern(pattern) {
  let result = '';
  for (let i = 0; i < pattern.length; i++) {
    if (pattern[i] === '\\' && i + 1 < pattern.length) {
      const next = pattern[++i];
      result += next === '0' && !/[0-9]/.test(pattern[i + 1] || '') ? '\\x00' : '\\' + next;
    } else result += pattern[i];
  }
  return result;
}
function portableSchema(schema) {
  if (!schema || typeof schema !== 'object') return schema;
  if (Array.isArray(schema)) return schema.map(portableSchema);
  const result = { ...schema };
  if (typeof result.pattern === 'string') result.pattern = portablePattern(result.pattern);
  // Walk schema locations, not instance data such as enum/default/examples.
  for (const key of ['properties', '$defs', 'definitions', 'dependentSchemas', 'dependencies', 'patternProperties']) {
    if (result[key] && typeof result[key] === 'object' && !Array.isArray(result[key])) {
      result[key] = Object.fromEntries(Object.entries(result[key]).map(([name, value]) => [
        key === 'patternProperties' ? portablePattern(name) : name,
        key === 'dependencies' && Array.isArray(value) ? value : portableSchema(value),
      ]));
    }
  }
  for (const key of ['items', 'additionalItems', 'additionalProperties', 'contains', 'propertyNames',
    'if', 'then', 'else', 'not', 'unevaluatedProperties', 'unevaluatedItems', 'contentSchema',
    'allOf', 'anyOf', 'oneOf', 'prefixItems']) {
    if (key in result) result[key] = portableSchema(result[key]);
  }
  return result;
}
function subagentBody(body, model) {
  const copy = { ...body, model };
  // Drop client identity and Anthropic-only request configuration.
  for (const key of ['metadata', 'context_management', 'container', 'mcp_servers',
    'service_tier', 'inference_geo', 'betas']) delete copy[key];
  // Claude Code can introduce tool schemas mid-conversation. Providers that
  // support tool_addition by reference may not support inline definitions yet.
  // Match Claude's own fallback: declare the schemas in tools and keep named
  // references at their original positions. Never walk arbitrary tool inputs.
  const inlineTools = new Map();
  function normalizeContent(content) {
    if (!Array.isArray(content)) return content;
    return content.map(block => {
      if (block?.type === 'tool_addition' && block.tool?.type === 'tool_definition') {
        const definition = block.tool.definition;
        if (!definition || typeof definition.name !== 'string' || !definition.name.trim() ||
            !definition.input_schema || typeof definition.input_schema !== 'object' ||
            Array.isArray(definition.input_schema)) throw new Error('Invalid inline tool definition');
        inlineTools.set(definition.name, definition);
        return { ...block, tool: { type: 'tool_reference', name: definition.name } };
      }
      if (block?.type === 'tool_result' && Array.isArray(block.content)) {
        return { ...block, content: normalizeContent(block.content) };
      }
      return block;
    });
  }
  if (Array.isArray(copy.messages)) {
    copy.messages = copy.messages.map(message => ({ ...message, content: normalizeContent(message.content) }));
  }
  if (Array.isArray(copy.system)) copy.system = normalizeContent(copy.system);
  if (inlineTools.size) {
    // Explicit top-level schemas take precedence over historical definitions.
    const explicitTools = Array.isArray(copy.tools) ? copy.tools : [];
    for (const tool of explicitTools) inlineTools.delete(tool.name);
    copy.tools = [...inlineTools.values(), ...explicitTools];
  }
  if (Array.isArray(copy.tools)) {
    copy.tools = copy.tools
      .filter(tool => !String(tool.type || '').startsWith('advisor') && tool.name !== 'advisor')
      .map(tool => tool.input_schema ? { ...tool, input_schema: portableSchema(tool.input_schema) } : tool);
    if (copy.tool_choice?.type === 'tool' && !copy.tools.some(tool => tool.name === copy.tool_choice.name)) {
      throw new Error('Selected tool is unavailable on the subagent route');
    }
  }
  return copy;
}

export function createProxy(options = {}) {
  const anthropic = new URL(options.anthropicUrl || 'https://api.anthropic.com');
  const getConfig = options.getConfig || (() => loadSubagentConfig(options.configPath));
  const getKey = options.getKey || readKey;
  const counters = { anthropic: 0, subagent: 0, errors: 0, inFlight: 0 };
  const server = http.createServer(async (req, res) => {
    // Prevent browser-originated requests to this loopback service.
    if (req.headers.origin) { errorResponse(res, 403, 'Browser requests are not accepted'); return; }
    if (req.url === '/healthz' && req.method === 'GET') {
      let subagent;
      try {
        const config = validateSubagentConfig(getConfig());
        subagent = { alias: subagentAlias, model: config.model, baseUrl: config.base_url,
          authType: config.auth_type, ready: config.auth_type === 'none' || Boolean(getKey(config)) };
      } catch { subagent = { ready: false, error: 'Invalid or unreadable subagent configuration' }; }
      res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify({ status: 'ok', subagent, counters }));
      return;
    }
    if (!req.url?.startsWith('/v1/') || req.url.startsWith('//')) {
      errorResponse(res, 404, 'Only /v1/ API paths are supported'); return;
    }
    if (!['GET', 'POST'].includes(req.method)) { errorResponse(res, 405, 'Method not supported'); return; }
    let raw, body;
    try {
      const chunks = []; let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > maxBody) { errorResponse(res, 413, 'Request body exceeds 64 MiB'); return; }
        chunks.push(chunk);
      }
      raw = Buffer.concat(chunks);
      if (raw.length) body = decodeJson(raw, req.headers['content-encoding']);
    } catch { errorResponse(res, 400, 'Request body must be valid supported JSON'); return; }
    const isSubagent = body && typeof body.model === 'string' && (body.model === subagentAlias || legacyModels.includes(body.model));
    let upstreamBody = raw;
    let headers, upstreamUrl;
    if (isSubagent) {
      let config;
      try { config = validateSubagentConfig(getConfig()); }
      catch { errorResponse(res, 503, 'Subagent configuration is invalid or unreadable'); return; }
      // Do not silently reroute an old DeepSeek session to a newly selected provider.
      if (body.model !== subagentAlias && config.model !== 'deepseek-flash' && config.model !== 'deepseek-v4-flash') {
        errorResponse(res, 409, 'Subagent provider changed; restart this session with claude-split'); return;
      }
      const key = getKey(config);
      if (config.auth_type !== 'none' && (!key || /[\r\n]/.test(key))) { errorResponse(res, 503, 'Subagent API key is unavailable'); return; }
      upstreamUrl = providerUrl(config.base_url, req.url);
      try { upstreamBody = Buffer.from(JSON.stringify(subagentBody(body, config.model))); }
      catch { errorResponse(res, 400, 'Subagent tool definitions are invalid or unavailable'); return; }
      // Never forward Claude credentials, cookies, identity headers or query parameters.
      headers = ['Content-Type', 'application/json', 'Accept', 'text/event-stream, application/json',
        'Anthropic-Version', '2023-06-01', 'Content-Length', String(upstreamBody.length)];
      if (config.auth_type === 'x-api-key') headers.push('X-Api-Key', key);
      else if (config.auth_type === 'bearer') headers.push('Authorization', `Bearer ${key}`);
      // OpenCode Go routes on a stable per-conversation session ID and wants a self-identifying UA.
      if (upstreamUrl.hostname === 'opencode.ai' || upstreamUrl.hostname.endsWith('.opencode.ai')) {
        const sid = req.headers['x-claude-code-session-id'] || req.headers['x-opencode-session'] || processSessionId;
        headers.push('x-opencode-session', String(sid), 'User-Agent', 'claude-split-subagent/1.0');
      }
    } else {
      upstreamUrl = new URL(anthropic);
      upstreamUrl.pathname = anthropic.pathname.replace(/\/$/, '') + req.url.split('?')[0];
      upstreamUrl.search = req.url.includes('?') ? req.url.slice(req.url.indexOf('?')) : '';
      // Preserve original Claude body bytes and end-to-end header values.
      headers = rawForwardHeaders(req.rawHeaders);
    }
    headers.push('Host', upstreamUrl.host);
    const route = isSubagent ? 'subagent' : 'anthropic';
    counters[route]++; counters.inFlight++;
    let finished = false;
    const finish = () => { if (!finished) { finished = true; counters.inFlight--; } };
    res.once('close', finish);
    const transport = upstreamUrl.protocol === 'https:' ? https : http;
    const outgoing = transport.request(upstreamUrl, { method: req.method, headers }, incoming => {
      res.writeHead(incoming.statusCode, rawForwardHeaders(incoming.rawHeaders));
      res.flushHeaders();
      incoming.on('error', () => { counters.errors++; res.destroy(); });
      incoming.pipe(res);
    });
    outgoing.setTimeout(300_000, () => outgoing.destroy(new Error('Upstream idle timeout')));
    outgoing.on('error', () => { counters.errors++; errorResponse(res, 502, 'Upstream connection failed'); });
    res.once('close', () => { if (!res.writableFinished) outgoing.destroy(); });
    outgoing.end(upstreamBody);
  });
  server.requestTimeout = 120_000;
  server.headersTimeout = 30_000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const server = createProxy();
  server.listen(3457, '127.0.0.1', () => console.log('Claude subagent proxy listening on http://127.0.0.1:3457'));
  server.on('error', error => { console.error(`Proxy startup failed: ${error.code || 'unknown error'}`); process.exit(1); });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
    server.close();
    setTimeout(() => process.exit(0), 3000).unref();
  });
}
