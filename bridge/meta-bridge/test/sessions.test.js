'use strict';
// Session state machine + envelope normalization unit tests (no sockets).

const test = require('node:test');
const assert = require('node:assert');
const { SessionManager } = require('../src/sessions/manager');
const { extractText, normalizePhone, toJid } = require('../src/whatsapp');

function makeFakeTransport() {
  const t = new (require('node:events').EventEmitter)();
  t.connect = async () => { t.emit('status', 'CONNECTED'); };
  t.disconnect = async () => { t.emit('status', 'DISCONNECTED'); };
  return t;
}

test('session states flow DISCONNECTED→CONNECTING→CONNECTED', async () => {
  const t = makeFakeTransport();
  const mgr = new SessionManager('whatsapp', t, { baseMs: 5, maxMs: 20 });
  const seen = [];
  mgr.on('state', (s) => seen.push(s.to));
  mgr.start();
  await new Promise(r => setTimeout(r, 30));
  assert.strictEqual(mgr.state, 'CONNECTED');
  assert.deepStrictEqual(seen, ['CONNECTING', 'CONNECTED']);
  await mgr.stop();
});

test('transport failure → DISCONNECTED then backoff reconnect', async () => {
  let fail = true;
  const t = makeFakeTransport();
  t.connect = async () => {
    if (fail) throw new Error('network down');
    t.emit('status', 'CONNECTED');
  };
  const mgr = new SessionManager('whatsapp', t, { baseMs: 5, maxMs: 20 });
  mgr.start();
  await new Promise(r => setTimeout(r, 10));
  assert.strictEqual(mgr.state, 'DISCONNECTED');
  assert.strictEqual(mgr.lastError, 'network down');
  fail = false;
  await new Promise(r => setTimeout(r, 40)); // backoff retry succeeds
  assert.strictEqual(mgr.state, 'CONNECTED');
  await mgr.stop();
});

test('AUTH_REQUIRED does not spin a reconnect loop', async () => {
  const t = makeFakeTransport();
  const mgr = new SessionManager('whatsapp', t, { baseMs: 5, maxMs: 20 });
  const seen = [];
  mgr.on('state', (s) => seen.push(s.to));
  mgr._setStatus('AUTH_REQUIRED', { error: 'logged out' });
  assert.strictEqual(mgr.state, 'AUTH_REQUIRED');
  assert.ok(!mgr._timer); // no scheduled reconnect — owner must pair
  assert.ok(seen.includes('AUTH_REQUIRED'));
  await mgr.stop();
});

test('reconnect() clears timer and reconnects', async () => {
  const t = makeFakeTransport();
  const mgr = new SessionManager('whatsapp', t, { baseMs: 5, maxMs: 20 });
  mgr.start();
  await new Promise(r => setTimeout(r, 20));
  await mgr.reconnect();
  assert.strictEqual(mgr.state, 'CONNECTED');
  await mgr.stop();
});

test('snapshot shape matches AmanCode health expectations', async () => {
  const t = makeFakeTransport();
  const mgr = new SessionManager('whatsapp', t);
  const snap = mgr.snapshot();
  assert.deepStrictEqual(Object.keys(snap).sort(),
    ['channel', 'connected_since', 'last_error', 'last_event_at', 'state']);
  assert.strictEqual(snap.state, 'DISCONNECTED');
});

// ---- envelope normalization (Baileys shape → bridge envelope) -------------

test('normalizePhone strips JID device/session parts', () => {
  assert.strictEqual(normalizePhone('201234567890@s.whatsapp.net'),
    '201234567890');
  assert.strictEqual(normalizePhone('201234567890:12@s.whatsapp.net'),
    '201234567890');
  assert.strictEqual(normalizePhone('201234567890.0:34@s.whatsapp.net'),
    '2012345678900');
});

test('toJid produces E164 JID', () => {
  assert.strictEqual(toJid('+20 123 456 7890'),
    '201234567890@s.whatsapp.net');
  assert.throws(() => toJid(''));
});

test('extractText maps Baileys message shapes', () => {
  assert.deepStrictEqual(
    extractText({ message: { conversation: 'hello' } }),
    { type: 'text', text: 'hello' });
  const img = extractText({ message: {
    imageMessage: { caption: 'look', url: 'x' } } });
  assert.strictEqual(img.type, 'image');
  assert.strictEqual(img.text, 'look');
  assert.ok(img.media_ref);
  const reply = extractText({ message: {
    extendedTextMessage: { text: 're', contextInfo: { stanzaId: 'ORIG1' } } } });
  assert.strictEqual(reply.reply_to, 'ORIG1');
  assert.strictEqual(extractText({ message: {} }).type, 'unsupported');
});
