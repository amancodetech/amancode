'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { InstagramTransport, normalizeId, extractText } = require('../src/instagram');

test('normalizeId strips invalid chars preserving IG user/thread format', () => {
  assert.strictEqual(normalizeId('1234567890'), '1234567890');
  assert.strictEqual(normalizeId('  user_123-abc  '), 'user_123-abc');
});

test('extractText extracts text from string or message object', () => {
  assert.deepStrictEqual(extractText('hello'), { type: 'text', text: 'hello' });
  assert.deepStrictEqual(extractText({ text: 'hi there' }), { type: 'text', text: 'hi there', reply_to: undefined });
  assert.deepStrictEqual(
    extractText({ text: 'reply text', replyTo: 'ig_mid_123' }),
    { type: 'text', text: 'reply text', reply_to: 'ig_mid_123' }
  );
});

test('InstagramTransport emits AUTH_REQUIRED when session.json is missing', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ig-test-'));
  const config = { dataDir: tmpDir, shadow: false };
  const transport = new InstagramTransport(config);

  const statuses = [];
  transport.on('status', (s, details) => statuses.push({ state: s, details }));

  await transport.connect();
  assert.strictEqual(statuses.length, 1);
  assert.strictEqual(statuses[0].state, 'AUTH_REQUIRED');
  assert.match(statuses[0].details.error, /session\.json missing/);
});

test('InstagramTransport connects with driver and receives inbound messages', async () => {
  let fakeListener = null;
  const mockDriver = async () => ({
    onInboundMessage: (cb) => { fakeListener = cb; },
    sendMessage: (body, threadId, cb) => {
      cb(null, { item_id: 'ig_sent_999' });
    },
  });

  const config = { dataDir: '/tmp', shadow: false };
  const transport = new InstagramTransport(config, { driver: mockDriver });

  const statuses = [];
  const inbounds = [];
  transport.on('status', (s) => statuses.push(s));
  transport.on('inbound', (env) => inbounds.push(env));

  await transport.connect();
  assert.deepStrictEqual(statuses, ['CONNECTED']);

  // Simulate inbound message
  fakeListener({
    user_id: '1122334455',
    username: 'ig_customer',
    item_id: 'ig_item_001',
    text: 'مرحبا من إنستغرام',
    timestamp: 1724930000000,
    thread_id: '34028236684171030094912813',
  });

  assert.strictEqual(inbounds.length, 1);
  const env = inbounds[0];
  assert.strictEqual(env.channel, 'instagram');
  assert.strictEqual(env.event_type, 'message.received');
  assert.strictEqual(env.external_message_id, 'ig_item_001');
  assert.strictEqual(env.sender.external_id, '1122334455');
  assert.strictEqual(env.message.text, 'مرحبا من إنستغرام');

  // Test outbound sendText
  const sent = await transport.sendText({ to: '34028236684171030094912813', text: 'أهلاً بك' });
  assert.strictEqual(sent.external_message_id, 'ig_sent_999');

  // Disconnect
  await transport.disconnect();
  assert.strictEqual(statuses.includes('DISCONNECTED'), true);
});

test('InstagramTransport clamps text to 1000 chars as per spec', async () => {
  let sentBody = '';
  const mockDriver = async () => ({
    sendMessage: (body, threadId, cb) => {
      sentBody = body;
      cb(null, { item_id: 'ig_sent_clamp' });
    },
  });

  const config = { dataDir: '/tmp', shadow: false };
  const transport = new InstagramTransport(config, { driver: mockDriver });
  await transport.connect();

  await transport.sendText({ to: '123', text: 'x'.repeat(2500) });
  assert.strictEqual(sentBody.length, 1000);
});
