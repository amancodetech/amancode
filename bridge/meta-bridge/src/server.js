'use strict';
// meta-bridge HTTP server — the local bridge surface AmanCore talks to
// (owner spec §19-23). Token-checked on every request.

const http = require('node:http');
const config = require('./core/config');
const log = require('./core/log');
log.setLevel(config.logLevel);

const { Router, readBody, sendJson } = require('./core/http');
const { BridgeError, statusToCategory } = require('./core/errors');
const { SessionManager } = require('./sessions/manager');
const { IngressForwarder } = require('./transport/ingress');
const { WhatsAppTransport } = require('./whatsapp');
const { FacebookTransport } = require('./facebook');
const { InstagramTransport } = require('./instagram');
const metrics = require('./metrics');

const startedAt = Date.now();

// ---- transports + sessions ----------------------------------------------

const transports = new Map();   // channel -> transport
const sessions = new Map();     // channel -> SessionManager

function buildWhatsapp() {
  const transport = new WhatsAppTransport(config);
  const manager = new SessionManager('whatsapp', transport, {
    baseMs: config.reconnectBaseMs,
    maxMs: config.reconnectMaxMs,
  });
  transport.on('inbound', (envelope) => {
    metrics.incr('inbound', 'whatsapp');
    forwarder.enqueue(envelope);
  });
  transports.set('whatsapp', transport);
  sessions.set('whatsapp', manager);
  return manager;
}

function buildFacebook() {
  const transport = new FacebookTransport(config);
  const manager = new SessionManager('facebook', transport, {
    baseMs: config.reconnectBaseMs,
    maxMs: config.reconnectMaxMs,
  });
  transport.on('inbound', (envelope) => {
    metrics.incr('inbound', 'facebook');
    forwarder.enqueue(envelope);
  });
  transports.set('facebook', transport);
  sessions.set('facebook', manager);
  return manager;
}

function buildInstagram() {
  const transport = new InstagramTransport(config);
  const manager = new SessionManager('instagram', transport, {
    baseMs: config.reconnectBaseMs,
    maxMs: config.reconnectMaxMs,
  });
  transport.on('inbound', (envelope) => {
    metrics.incr('inbound', 'instagram');
    forwarder.enqueue(envelope);
  });
  transports.set('instagram', transport);
  sessions.set('instagram', manager);
  return manager;
}

const forwarder = new IngressForwarder(config);

// channel factories — invoked in start() so tests can inject fakes
const channelFactories = new Map();

function registerChannel(name, factory) {
  channelFactories.set(name, factory);
}

registerChannel('whatsapp', buildWhatsapp);
registerChannel('facebook', buildFacebook);
registerChannel('instagram', buildInstagram);

function buildChannels() {
  for (const ch of config.channels) {
    const factory = channelFactories.get(ch);
    if (factory) factory();
    else log.warn('no transport factory for channel', { channel: ch });
  }
}

// ---- router ---------------------------------------------------------------

const router = new Router();

function auth(req) {
  const token = req.headers['x-bridge-token'] || '';
  const a = Buffer.from(String(token));
  const b = Buffer.from(config.bridgeToken);
  if (a.length !== b.length || !require('node:crypto').timingSafeEqual(a, b)) {
    throw new BridgeError('unauthorized', 'auth_required', 403);
  }
}

function guard(handler) {
  return async (req, res, params, query) => {
    try {
      auth(req);
      await handler(req, res, params, query);
    } catch (err) {
      if (err instanceof BridgeError) {
        sendJson(res, err.status, err.toJSON());
        return;
      }
      const category = err.category || statusToCategory(500);
      log.error('request failed', {
        method: req.method, url: req.url,
        error: err.message, category,
      });
      const status = err.category === 'auth_required' ? 401
        : err.category === 'invalid_request' ? 400
        : err.category === 'temporary' ? 503
        : 500;
      sendJson(res, status, {
        error: err.message, category,
      });
    }
  };
}

router.get('/v1/health', guard(async (req, res) => {
  const health = {
    status: 'ok',
    uptime_seconds: Math.floor((Date.now() - startedAt) / 1000),
    shadow: config.shadow,
    channels: {},
    ingress_queue_depth: forwarder.depth(),
  };
  for (const [ch, mgr] of sessions) {
    health.channels[ch] = mgr.snapshot();
  }
  // degraded when any configured channel is not CONNECTED
  const states = [...sessions.values()].map(m => m.state);
  if (states.length && !states.every(s => s === 'CONNECTED')) {
    health.status = 'degraded';
  }
  sendJson(res, 200, health);
}));

router.get('/v1/sessions', guard(async (req, res) => {
  const out = {};
  for (const [ch, mgr] of sessions) out[ch] = mgr.snapshot();
  sendJson(res, 200, { sessions: out });
}));

router.post('/v1/session/reconnect', guard(async (req, res, params) => {
  const body = JSON.parse((await readBody(req)).toString() || '{}');
  const channel = String(body.channel || params.channel || '');
  const mgr = sessions.get(channel);
  if (!mgr) {
    throw new BridgeError(`unknown channel: ${channel}`, 'not_found', 404);
  }
  await mgr.reconnect();
  sendJson(res, 200, { channel, session: mgr.snapshot() });
}));

router.post('/v1/messages/send', guard(async (req, res) => {
  const body = JSON.parse((await readBody(req)).toString() || '{}');
  const channel = String(body.channel || 'whatsapp');
  const transport = transports.get(channel);
  if (!transport) {
    throw new BridgeError(
      `channel not configured on this bridge: ${channel}`, 'not_found', 404);
  }
  const msg = body.message || {};
  const type = String(msg.type || 'text');
  metrics.incr('outbound_attempt', channel);

  let result;
  try {
    if (type === 'text') {
      result = await transport.sendText({
        to: body.to, text: msg.text, replyTo: msg.reply_to,
      });
    } else if (['image', 'audio', 'video', 'document'].includes(type)) {
      result = await transport.sendMedia({
        to: body.to, type, base64: msg.media?.base64,
        caption: msg.caption, filename: msg.media?.filename,
        replyTo: msg.reply_to,
      });
    } else {
      throw new BridgeError(
        `unsupported message type: ${type}`, 'invalid_request', 400);
    }
  } catch (err) {
    const category = err.category || statusToCategory(500);
    metrics.incr(`outbound_${category}`, channel);
    throw err;
  }
  metrics.incr(result.would_send ? 'outbound_shadow' : 'outbound_success', channel);
  if (result.external_message_id) {
    messageStatuses.set(result.external_message_id, {
      id: result.external_message_id,
      status: result.would_send ? 'shadow_held' : 'sent',
      recorded_at: new Date().toISOString(),
    });
  }
  sendJson(res, 200, {
    message_id: result.external_message_id,
    to: result.to,
    would_send: result.would_send ?? undefined,
    shadow: result.shadow ?? undefined,
  });
}));

router.post('/v1/messages/react', guard(async (req, res) => {
  const body = JSON.parse((await readBody(req)).toString() || '{}');
  const channel = String(body.channel || 'whatsapp');
  const transport = transports.get(channel);
  if (!transport) {
    throw new BridgeError(
      `channel not configured on this bridge: ${channel}`, 'not_found', 404);
  }
  const result = await transport.react({
    to: body.to, targetMessageId: body.target_message_id,
    emoji: body.emoji,
  });
  sendJson(res, 200, { ok: true, ...result });
}));

router.post('/v1/messages/read', guard(async (req, res) => {
  const body = JSON.parse((await readBody(req)).toString() || '{}');
  const channel = String(body.channel || 'whatsapp');
  const transport = transports.get(channel);
  if (!transport) {
    throw new BridgeError(
      `channel not configured on this bridge: ${channel}`, 'not_found', 404);
  }
  const result = await transport.markRead({
    to: body.to, messageIds: body.message_ids,
  });
  sendJson(res, 200, { ok: true, ...result });
}));

router.get('/v1/messages/:id', guard(async (req, res, params) => {
  // Reconciliation hook (spec §45): outcome lookup for a previously
  // submitted message. Baileys keeps no durable outbox — status comes from
  // our own send result cache.
  const rec = messageStatuses.get(params.id);
  if (!rec) {
    throw new BridgeError('message id unknown', 'not_found', 404);
  }
  sendJson(res, 200, rec);
}));

const messageStatuses = new Map(); // external_message_id -> status record

// ---- server ----------------------------------------------------------------

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://localhost');
  const match = router.match(req.method, u.pathname);
  metrics.incr('http_requests');
  if (!match) {
    sendJson(res, 404, { error: 'not found' });
    return;
  }
  match.handler(req, res, match.params, u.searchParams)
    .catch((err) => {
      log.error('unhandled route error', { url: req.url, error: err.message });
      if (!res.headersSent) {
        sendJson(res, 500, { error: 'internal', category: 'temporary' });
      }
    });
});

// record send outcomes for reconciliation
const origSend = router; // (routes above push statuses via wrap below)
function noteStatus(id, status) {
  if (id) messageStatuses.set(id, {
    id, status, recorded_at: new Date().toISOString(),
  });
}

async function start() {
  if (sessions.size === 0) module.exports.buildChannels();
  forwarder.start();
  await new Promise((resolve) => server.listen(config.port, config.host, resolve));
  log.info('meta-bridge listening', {
    host: config.host, port: config.port, shadow: config.shadow,
    channels: config.channels,
  });
  for (const [, mgr] of sessions) mgr.start();
  return server;
}

async function stop() {
  for (const [, mgr] of sessions) await mgr.stop();
  await forwarder.stop();
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
}

module.exports = {
  server, router, start, stop, noteStatus, messageStatuses,
  transports, sessions, forwarder, registerChannel, buildChannels,
};

if (require.main === module) {
  start().catch((err) => {
    log.error('meta-bridge failed to start', { error: err.message });
    process.exit(1);
  });
  process.on('SIGTERM', () => stop().then(() => process.exit(0)));
  process.on('SIGINT', () => stop().then(() => process.exit(0)));
}
