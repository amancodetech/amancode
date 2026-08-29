'use strict';
// HTTP surface contract tests — mirror of AmanCore's bridge expectations.

const test = require('node:test');
const assert = require('node:assert');
const { after } = require('node:test');
const {
  startBridge, call, sleep, stubAmanCore, receivedEnvelopes, resetReceived,
  setFailures,
} = require('./_helpers');

// let the runner exit: close the stub AmanCore after all tests
after(async () => {
  stubAmanCore.closeAllConnections();
  await new Promise((resolve) => stubAmanCore.close(resolve));
});

test('health requires the bridge token', async () => {
  const { bridge, baseUrl } = await startBridge();
  const noAuth = await call(baseUrl, 'GET', '/v1/health', null, 'wrong');
  assert.strictEqual(noAuth.status, 403);
  const ok = await call(baseUrl, 'GET', '/v1/health');
  assert.strictEqual(ok.status, 200);
  assert.strictEqual(ok.body.status, 'ok');
  await bridge.stop();
});

test('health reports session state per channel', async () => {
  const { bridge, baseUrl } = await startBridge();
  const ok = await call(baseUrl, 'GET', '/v1/health');
  assert.ok(ok.body.channels.whatsapp);
  assert.strictEqual(ok.body.channels.whatsapp.state, 'CONNECTED');
  await bridge.stop();
});

test('send text returns external message id', async () => {
  const { bridge, transport, baseUrl } = await startBridge();
  const res = await call(baseUrl, 'POST', '/v1/messages/send', {
    channel: 'whatsapp',
    to: '201234567890',
    message: { type: 'text', text: 'مرحبا' },
  });
  assert.strictEqual(res.status, 200);
  assert.match(res.body.message_id, /^FAKE/);
  assert.strictEqual(transport.sent[0].op, 'sendText');
  await bridge.stop();
});

test('send to unconfigured channel → 404 not_found', async () => {
  const { bridge, baseUrl } = await startBridge();
  const res = await call(baseUrl, 'POST', '/v1/messages/send', {
    channel: 'instagram', to: '123', message: { type: 'text', text: 'x' },
  });
  assert.strictEqual(res.status, 404);
  assert.strictEqual(res.body.category, 'not_found');
  await bridge.stop();
});

test('unknown message type → 400 invalid_request', async () => {
  const { bridge, baseUrl } = await startBridge();
  const res = await call(baseUrl, 'POST', '/v1/messages/send', {
    channel: 'whatsapp', to: '201234567890',
    message: { type: 'carrier_pigeon', text: 'x' },
  });
  assert.strictEqual(res.status, 400);
  assert.strictEqual(res.body.category, 'invalid_request');
  await bridge.stop();
});

test('react and read endpoints', async () => {
  const { bridge, transport, baseUrl } = await startBridge();
  const r = await call(baseUrl, 'POST', '/v1/messages/react', {
    channel: 'whatsapp', to: '201234567890',
    target_message_id: 'MSG1', emoji: '👍',
  });
  assert.strictEqual(r.status, 200);
  const rd = await call(baseUrl, 'POST', '/v1/messages/read', {
    channel: 'whatsapp', to: '201234567890',
    message_ids: ['MSG1', 'MSG2'],
  });
  assert.strictEqual(rd.status, 200);
  assert.strictEqual(rd.body.read, 2);
  assert.strictEqual(transport.sent[0].op, 'react');
  await bridge.stop();
});

test('ingress: inbound event reaches AmanCore stub and spool is cleaned', async () => {
  const { bridge, baseUrl } = await startBridge();
  resetReceived();
  const transport = bridge.transports.get('whatsapp');
  transport.emit('inbound', {
    channel: 'whatsapp',
    event_type: 'message.received',
    external_message_id: 'TESTID1',
    sender: { external_id: '201234567890', name: 'Omar' },
    timestamp: '2026-08-29T10:00:00Z',
    message: { type: 'text', text: 'أهلاً' },
  });
  await sleep(1200);
  assert.strictEqual(receivedEnvelopes.length, 1);
  assert.strictEqual(receivedEnvelopes[0].external_message_id, 'TESTID1');
  assert.strictEqual(
    require('node:fs').readdirSync(
      require('node:path').join(process.env.BRIDGE_DATA_DIR, 'ingress_spool')
    ).filter(f => f.endsWith('.json')).length, 0);
  await bridge.stop();
});

test('ingress retries on 5xx and eventually delivers', async () => {
  const { bridge, baseUrl } = await startBridge();
  resetReceived();
  setFailures(2); // first two attempts fail with 503
  const transport = bridge.transports.get('whatsapp');
  transport.emit('inbound', {
    channel: 'whatsapp',
    event_type: 'message.received',
    external_message_id: 'RETRYID1',
    sender: { external_id: '201234567890' },
    timestamp: '2026-08-29T10:00:00Z',
    message: { type: 'text', text: 'retry me' },
  });
  await sleep(4500); // backoff: ~1s + ~2s + margin
  assert.strictEqual(receivedEnvelopes.length, 1);
  assert.strictEqual(receivedEnvelopes[0].external_message_id, 'RETRYID1');
  setFailures(0);
  await bridge.stop();
});

test('shadow mode holds the send (would_send, no delivery)', async () => {
  const { bridge, baseUrl } = await startBridge();
  bridge.transports.get('whatsapp').shadow = true;
  const res = await call(baseUrl, 'POST', '/v1/messages/send', {
    channel: 'whatsapp', to: '201234567890',
    message: { type: 'text', text: 'shadow' },
  });
  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.body.would_send, true);
  assert.strictEqual(res.body.shadow, true);
  assert.strictEqual(res.body.message_id, null);
  await bridge.stop();
});

test('reconnect endpoint resets the session', async () => {
  const { bridge, baseUrl } = await startBridge();
  const res = await call(baseUrl, 'POST', '/v1/session/reconnect',
    { channel: 'whatsapp' });
  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.body.session.state, 'CONNECTED');
  await bridge.stop();
});
