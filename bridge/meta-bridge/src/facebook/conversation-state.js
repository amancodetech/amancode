'use strict';
// ConversationState — tracks last-seen messages per conversation to prevent duplicates.

const fs = require('node:fs');
const path = require('node:path');
const log = require('../core/log');

class ConversationState {
  constructor(config, opts = {}) {
    this.config = config;
    this.stateFile = opts.stateFile ||
      path.join(config.dataDir, 'facebook_conversation_state.json');
    this._state = this._load();
  }

  _load() {
    try {
      if (fs.existsSync(this.stateFile)) {
        return JSON.parse(fs.readFileSync(this.stateFile, 'utf8'));
      }
    } catch (err) {
      log.warn('failed to load conversation state', { error: err.message });
    }
    return {};
  }

  _save() {
    try {
      fs.mkdirSync(path.dirname(this.stateFile), { recursive: true });
      fs.writeFileSync(this.stateFile, JSON.stringify(this._state, null, 2));
    } catch (err) {
      log.error('failed to save conversation state', { error: err.message });
    }
  }

  isDuplicate(conversationId, messageId) {
    const conv = this._state[conversationId];
    if (!conv) return false;
    return conv.last_seen_message_id === messageId;
  }

  update(conversationId, messageId, timestamp) {
    const prev = this._state[conversationId];
    this._state[conversationId] = {
      conversation_id: conversationId,
      last_seen_message_id: messageId,
      last_seen_timestamp: timestamp || new Date().toISOString(),
      last_message_signature: `${conversationId}:${messageId}`,
      updated_at: new Date().toISOString(),
    };
    this._save();
    return prev;
  }

  get(conversationId) {
    return this._state[conversationId] || null;
  }

  getAll() {
    return { ...this._state };
  }

  cleanup(maxAge = 7 * 24 * 60 * 60 * 1000) {
    const cutoff = Date.now() - maxAge;
    let removed = 0;
    for (const [id, state] of Object.entries(this._state)) {
      const ts = new Date(state.updated_at).getTime();
      if (ts < cutoff) {
        delete this._state[id];
        removed++;
      }
    }
    if (removed > 0) {
      this._save();
      log.info('conversation state cleanup', { removed });
    }
    return removed;
  }
}

module.exports = { ConversationState };
