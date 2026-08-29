'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { FacebookTransport, normalizeId, extractText } = require('../src/facebook');

test('normalizeId strips invalid chars preserving PSID format', () => {
  assert.strictEqual(normalizeId('1234567890'), '1234567890');
  assert.strictEqual(normalizeId('  user-123_456  '), 'user-123_456');
  assert.strictEqual(normalizeId('abc@facebook.com!'), 'abcfacebookcom');
});

test('extractText extracts text from string or message object', () => {
  assert.deepStrictEqual(extractText('hello'), { type: 'text', text: 'hello' });
  assert.deepStrictEqual(extractText({ body: 'hi there' }), { type: 'text', text: 'hi there', reply_to: undefined });
  assert.deepStrictEqual(
    extractText({ body: 'reply text', messageReply: { messageID: 'mid123' } }),
    { type: 'text', text: 'reply text', reply_to: 'mid123' }
  );
});

test('FacebookTransport emits AUTH_REQUIRED when appstate.json is missing', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fb-test-'));
  const config = { dataDir: tmpDir, shadow: false };
  const transport = new FacebookTransport(config);

  const statuses = [];
  transport.on('status', (s, details) => statuses.push({ state: s, details }));

  await transport.connect();
  assert.strictEqual(statuses.length, 1);
  assert.strictEqual(statuses[0].state, 'AUTH_REQUIRED');
  assert.match(statuses[0].details.error, /appstate\.json missing/);
});

test('FacebookTransport connects with driver and receives inbound messages', async () => {
  let fakeListener = null;
  const mockDriver = async () => ({
    listen: (cb) => {
      fakeListener = cb;
      return () => { fakeListener = null; };
    },
    sendMessage: (msg, threadId, cb) => {
      cb(null, { messageID: 'mid_sent_999' });
    },
    logout: (cb) => cb && cb(),
  });

  const config = { dataDir: '/tmp', shadow: false };
  const transport = new FacebookTransport(config, { driver: mockDriver });

  const statuses = [];
  const inbounds = [];
  transport.on('status', (s) => statuses.push(s));
  transport.on('inbound', (env) => inbounds.push(env));

  await transport.connect();
  assert.deepStrictEqual(statuses, ['CONNECTED']);

  // Simulate inbound message
  fakeListener(null, {
    type: 'message',
    senderID: '987654321',
    senderName: 'Test User',
    messageID: 'mid_inbound_123',
    body: 'مرحبا من فيسبوك',
    timestamp: 1724930000000,
    threadID: '987654321',
  });

  assert.strictEqual(inbounds.length, 1);
  const env = inbounds[0];
  assert.strictEqual(env.channel, 'facebook');
  assert.strictEqual(env.event_type, 'message.received');
  assert.strictEqual(env.external_message_id, 'mid_inbound_123');
  assert.strictEqual(env.sender.external_id, '987654321');
  assert.strictEqual(env.message.text, 'مرحبا من فيسبوك');

  // Test outbound sendText
  const sent = await transport.sendText({ to: '987654321', text: 'أهلاً بك' });
  assert.strictEqual(sent.external_message_id, 'mid_sent_999');
  assert.strictEqual(sent.to, '987654321');

  // Disconnect
  await transport.disconnect();
  assert.strictEqual(statuses.includes('DISCONNECTED'), true);
});

test('FacebookTransport shadow mode returns would_send without external send', async () => {
  let sentCalled = false;
  const mockDriver = async () => ({
    sendMessage: (msg, threadId, cb) => {
      sentCalled = true;
      cb(null, { messageID: 'mid_shadow' });
    },
  });

  const config = { dataDir: '/tmp', shadow: true };
  const transport = new FacebookTransport(config, { driver: mockDriver, shadow: true });
  await transport.connect();

  const res = await transport.sendText({ to: '12345', text: 'test shadow' });
  assert.strictEqual(res.would_send, true);
  assert.strictEqual(res.shadow, true);
  assert.strictEqual(sentCalled, false);
});
