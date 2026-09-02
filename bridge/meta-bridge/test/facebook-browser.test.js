'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { SelectorRegistry, SELECTORS } = require('../src/facebook/selectors');
const { ConversationState } = require('../src/facebook/conversation-state');
const { normalizeId, extractText } = require('../src/facebook/browser-transport');

// ---- SelectorRegistry tests ----

test('SelectorRegistry returns selectors by category and name', () => {
  const reg = new SelectorRegistry();
  assert.strictEqual(typeof reg.get('composer', 'messageInput'), 'string');
  assert.strictEqual(typeof reg.get('auth', 'loginForm'), 'string');
  assert.strictEqual(typeof reg.get('messenger', 'conversationList'), 'string');
});

test('SelectorRegistry throws on unknown category', () => {
  const reg = new SelectorRegistry();
  assert.throws(() => reg.get('nonexistent', 'foo'), /Unknown selector category/);
});

test('SelectorRegistry throws on unknown selector name', () => {
  const reg = new SelectorRegistry();
  assert.throws(() => reg.get('composer', 'nonexistent'), /Unknown selector/);
});

test('SelectorRegistry supports overrides', () => {
  const reg = new SelectorRegistry({ composer: { messageInput: 'custom-selector' } });
  assert.strictEqual(reg.get('composer', 'messageInput'), 'custom-selector');
  // other selectors remain unchanged
  assert.strictEqual(typeof reg.get('auth', 'loginForm'), 'string');
});

test('SelectorRegistry getAll returns entire category', () => {
  const reg = new SelectorRegistry();
  const auth = reg.getAll('auth');
  assert.ok(auth.loginForm);
  assert.ok(auth.loginButton);
  assert.ok(auth.twoFactorInput);
});

// ---- ConversationState tests ----

test('ConversationState tracks and deduplicates messages', () => {
  const state = new ConversationState({ dataDir: '/tmp' }, { stateFile: '/tmp/fb-test-conv-state.json' });
  // First message is not a duplicate
  assert.strictEqual(state.isDuplicate('conv1', 'msg1'), false);
  state.update('conv1', 'msg1', '2025-01-01T00:00:00Z');
  // Same message again is a duplicate
  assert.strictEqual(state.isDuplicate('conv1', 'msg1'), true);
  // Different message is not a duplicate
  assert.strictEqual(state.isDuplicate('conv1', 'msg2'), false);
  state.update('conv1', 'msg2', '2025-01-01T00:01:00Z');
  // Old message is now a duplicate
  assert.strictEqual(state.isDuplicate('conv1', 'msg1'), false);
  assert.strictEqual(state.isDuplicate('conv1', 'msg2'), true);
});

test('ConversationState returns state for a conversation', () => {
  const state = new ConversationState({ dataDir: '/tmp' }, { stateFile: '/tmp/fb-test-conv-state2.json' });
  state.update('conv1', 'msg1', '2025-01-01T00:00:00Z');
  const conv = state.get('conv1');
  assert.ok(conv);
  assert.strictEqual(conv.last_seen_message_id, 'msg1');
  assert.strictEqual(conv.conversation_id, 'conv1');
});

test('ConversationState returns null for unknown conversation', () => {
  const state = new ConversationState({ dataDir: '/tmp' }, { stateFile: '/tmp/fb-test-conv-state3.json' });
  assert.strictEqual(state.get('nonexistent'), null);
});

test('ConversationState cleanup removes old entries', () => {
  const stateFile = '/tmp/fb-test-conv-state4.json';
  const state = new ConversationState({ dataDir: '/tmp' }, { stateFile });
  state.update('old-conv', 'msg1', '2020-01-01T00:00:00Z');
  state.update('new-conv', 'msg2', new Date().toISOString());
  // Manually age the old entry
  const fs = require('node:fs');
  const raw = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  raw['old-conv'].updated_at = '2020-01-01T00:00:00Z';
  fs.writeFileSync(stateFile, JSON.stringify(raw));
  // Re-load from disk
  const state2 = new ConversationState({ dataDir: '/tmp' }, { stateFile });
  const removed = state2.cleanup(1000); // 1 second maxAge — old entry is way older
  assert.ok(removed >= 1);
  assert.ok(state2.get('new-conv')); // new entry survived
  assert.strictEqual(state2.get('old-conv'), null); // old entry removed
});

// ---- normalizeId tests ----

test('normalizeId strips invalid chars preserving PSID format', () => {
  assert.strictEqual(normalizeId('1234567890'), '1234567890');
  assert.strictEqual(normalizeId('  user-123_456  '), 'user-123_456');
  assert.strictEqual(normalizeId('abc@facebook.com!'), 'abcfacebookcom');
});

// ---- extractText tests ----

test('extractText extracts text from string or message object', () => {
  assert.deepStrictEqual(extractText('hello'), { type: 'text', text: 'hello' });
  assert.deepStrictEqual(extractText({ body: 'hi there' }), { type: 'text', text: 'hi there', reply_to: undefined });
  assert.deepStrictEqual(
    extractText({ body: 'reply text', messageReply: { messageID: 'mid123' } }),
    { type: 'text', text: 'reply text', reply_to: 'mid123' }
  );
});
