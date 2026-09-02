'use strict';
// Test harness: starts the meta-bridge HTTP server on an ephemeral port with
// a FAKE WhatsApp transport (no Baileys socket, no network) and an in-memory
// ingress forwarder pointed at a stub AmanCode endpoint.

const http = require('node:http');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

// config must exist before requiring src/server.js
process.env.AMANCODE_BRIDGE_TOKEN = 'test-bridge-token';
process.env.BRIDGE_INGRESS_TOKEN = 'test-ingress-token';
process.env.BRIDGE_PORT = '0'; // ephemeral
process.env.BRIDGE_DATA_DIR = fs.mkdtempSync(
  path.join(os.tmpdir(), 'meta-bridge-test-'));
process.env.BRIDGE_SHADOW = '';
process.env.BRIDGE_CHANNELS = 'whatsapp';
process.env.AMANCODE_BASE_URL = 'http://127.0.0.1:1'; // no real amancore

// Stub AmanCode: accepts /bridge/inbound, records acks, optionally fails
let amancoreFailures = 0;
const receivedEnvelopes = [];

const stubAmanCode = http.createServer((req, res) => {
  if (req.method === 'POST' && req.url === '/bridge/inbound') {
    if ((req.headers['x-bridge-token'] || '') !== 'test-ingress-token') {
      res.writeHead(403); res.end('{"error":"UNAUTHORIZED"}'); return;
    }
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', () => {
      const env = JSON.parse(Buffer.concat(chunks).toString());
      if (amancoreFailures > 0) {
        amancoreFailures--;
        res.writeHead(503); res.end('{"error":"TEMPORARY_UNAVAILABLE"}');
        return;
      }
      receivedEnvelopes.push(env);
      res.writeHead(200,
        { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        accepted: true, event_id: env.event_id || 'stub',
        duplicate: false,
      }));
    });
    return;
  }
  res.writeHead(404); res.end();
});

class FakeWhatsAppTransport extends EventEmitter {
  constructor() {
    super();
    this.user = { id: '1000000000@s.whatsapp.net' };
    this.connected = false;
    this.sent = [];
    this.shadow = false;
  }
  async connect() {
    this.connected = true;
    this.emit('status', 'CONNECTED');
  }
  async disconnect() {
    this.connected = false;
    this.emit('status', 'DISCONNECTED');
  }
  async sendText(args) {
    this.sent.push({ op: 'sendText', ...args });
    if (this.shadow) {
      return { would_send: true, shadow: true, external_message_id: null };
    }
    return { external_message_id: `FAKE${this.sent.length}`, to: args.to };
  }
  async sendMedia(args) {
    this.sent.push({ op: 'sendMedia', ...args });
    return { external_message_id: `FAKEM${this.sent.length}`, to: args.to };
  }
  async react(args) {
    this.sent.push({ op: 'react', ...args });
    return { external_message_id: args.targetMessageId };
  }
  async markRead(args) {
    this.sent.push({ op: 'markRead', ...args });
    return { read: (args.messageIds || []).length };
  }
}

let stubListening = false;

async function startBridge({ transport = new FakeWhatsAppTransport() } = {}) {
  // suppress real channel construction — inject the fake instead
  const bridge = require('../src/server');
  bridge.buildChannels = () => {
    const mgr = new (require('../src/sessions/manager').SessionManager)(
      'whatsapp', transport, {
        baseMs: bridge.forwarder.config.reconnectBaseMs || 2000,
        maxMs: 20000,
      });
    bridge.transports.set('whatsapp', transport);
    bridge.sessions.set('whatsapp', mgr);
    // mirror the real factory's ingress wiring
    transport.on('inbound', (envelope) => bridge.forwarder.enqueue(envelope));
  };
  // force a clean rebuild per test: stop+drop previous sessions/transports
  for (const [, mgr] of bridge.sessions) {
    try { await mgr.stop(); } catch { /* best effort */ }
  }
  bridge.sessions.clear();
  bridge.transports.clear();
  if (!stubListening) {
    await new Promise((resolve) => stubAmanCode.listen(0, '127.0.0.1', resolve));
    stubListening = true;
  }
  // point the forwarder at the stub
  const addr = stubAmanCode.address();
  bridge.forwarder.config.amancodeBaseUrl =
    `http://127.0.0.1:${addr.port}`;
  await bridge.start();
  const baddr = bridge.server.address();
  const baseUrl = `http://127.0.0.1:${baddr.port}`;
  // wait for the injected session to reach CONNECTED (max 2s)
  const mgr = bridge.sessions.get('whatsapp');
  for (let i = 0; i < 100 && (!mgr || mgr.state !== 'CONNECTED'); i++) {
    await sleep(20);
  }
  return { bridge, transport, baseUrl };
}

function call(baseUrl, method, p, body, token = 'test-bridge-token') {
  const data = body ? JSON.stringify(body) : null;
  return new Promise((resolve, reject) => {
    const req = http.request(new URL(p, baseUrl), {
      method,
      agent: false, // no keep-alive — lets server.close() return promptly
      headers: {
        ...(data ? { 'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data) } : {}),
        'X-Bridge-Token': token,
      },
    }, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {
        let parsed = null;
        try { parsed = JSON.parse(Buffer.concat(chunks).toString()); }
        catch { /* non-json */ }
        resolve({ status: res.statusCode, body: parsed });
      });
    });
    req.on('error', reject);
    if (data) req.end(data); else req.end();
  });
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

module.exports = {
  startBridge, call, sleep, stubAmanCode, receivedEnvelopes,
  setFailures: (n) => { amancoreFailures = n; },
  resetReceived: () => { receivedEnvelopes.length = 0; },
  FakeWhatsAppTransport,
};
