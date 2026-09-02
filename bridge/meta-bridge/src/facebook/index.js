'use strict';
// Facebook Messenger transport for local meta-bridge (owner spec §18/§22).
//
// Platform specifics live ONLY inside this module.
// Emits:
//   'status' (CONNECTED | CONNECTING | AUTH_REQUIRED | DISCONNECTED, { error? })
//   'inbound' (normalized bridge envelope)

const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const log = require('../core/log');
const { BridgeError } = require('../core/errors');

function normalizeId(id) {
  return String(id || '').replace(/[^A-Za-z0-9_\-]/g, '');
}

function extractText(m) {
  if (typeof m === 'string') return { type: 'text', text: m };
  const text = m.body || m.text || '';
  const replyTo = m.messageReply?.messageID || m.replyTo || undefined;
  return { type: 'text', text: String(text), reply_to: replyTo };
}

class FacebookTransport extends EventEmitter {
  constructor(config, opts = {}) {
    super();
    this.config = config;
    this.shadow = opts.shadow ?? config.shadow ?? false;
    this.sessionDir = opts.sessionDir ||
      path.join(config.dataDir, 'facebook_session');
    this.appStateFile = path.join(this.sessionDir, 'appstate.json');
    this.api = null;
    this._driver = opts.driver || null; // test seam for faking FB driver in tests
    this._expectDisconnect = false;
    this._stopListening = null;
  }

  async connect() {
    this._expectDisconnect = false;
    fs.mkdirSync(this.sessionDir, { recursive: true });

    // Test seam: inject fake driver if provided
    if (this._driver) {
      this.api = await this._driver({
        appStateFile: this.appStateFile,
        sessionDir: this.sessionDir,
      });
      this._setupListener();
      this.emit('status', 'CONNECTED');
      return;
    }

    if (!fs.existsSync(this.appStateFile)) {
      log.warn('facebook appstate missing', {
        channel: 'facebook',
        file: this.appStateFile,
        hint: 'place facebook session in appstate.json or run fb login script',
      });
      this.emit('status', 'AUTH_REQUIRED', {
        error: 'appstate.json missing — Facebook session required',
      });
      return;
    }

    let appState;
    try {
      const raw = fs.readFileSync(this.appStateFile, 'utf8');
      appState = JSON.parse(raw);
    } catch (err) {
      log.error('invalid facebook appstate.json', { error: err.message });
      this.emit('status', 'AUTH_REQUIRED', {
        error: `invalid appstate.json: ${err.message}`,
      });
      return;
    }

    try {
      let loginFn;
      try {
        const mod = require('ws3-fca');
        loginFn = mod.login || mod;
      } catch {
        try {
          const mod = require('facebook-chat-api');
          loginFn = mod.login || mod;
        } catch {
          try {
            const mod = require('@xaviabot/fca-unofficial');
            loginFn = mod.login || mod;
          } catch {
            log.warn('facebook library not installed', {
              channel: 'facebook',
              hint: 'npm install ws3-fca in meta-bridge',
            });
            this.emit('status', 'AUTH_REQUIRED', {
              error: 'facebook transport driver not installed',
            });
            return;
          }
        }
      }

      const loginOpts = {};
      const hasIUser = appState.some(c => (c.key || c.name) === 'i_user');
      const pageID = !hasIUser ? (process.env.FACEBOOK_PAGE_ID || this.options?.pageID) : undefined;
      if (pageID) {
        loginOpts.pageID = String(pageID);
        log.info('facebook attaching to pageID', { pageID });
      }

      await new Promise((resolve, reject) => {
        loginFn({ appState }, loginOpts, (err, api) => {
          if (err) return reject(err);
          this.api = api;
          this._setupListener();
          this.emit('status', 'CONNECTED');
          resolve();
        });
      });
    } catch (err) {
      log.error('facebook connection failed', { error: err.message });
      const isAuth = /login|auth|session|cookie/i.test(err.message || '');
      this.emit('status', isAuth ? 'AUTH_REQUIRED' : 'DISCONNECTED', {
        error: err.message,
      });
    }
  }

  _setupListener() {
    if (!this.api || (typeof this.api.listenMqtt !== 'function' && typeof this.api.listen !== 'function')) {
      return;
    }

    const onEvent = (err, message) => {
      if (err) {
        log.error('facebook listener error', { error: err.message });
        if (this.api && typeof this.api.listen === 'function' && !this._triedHttpListen) {
          this._triedHttpListen = true;
          log.info('facebook falling back to HTTP listener');
          try {
            this._stopListening = this.api.listen(onEvent);
          } catch (e) {
            log.error('facebook fallback listen failed', { error: e.message });
          }
        }
        return;
      }
      if (!message) return;

      log.info('facebook raw event', {
        type: message.type,
        threadID: message.threadID,
        senderID: message.senderID,
        has_body: Boolean(message.body),
      });

      const isMessage = message.type === 'message' ||
        message.type === 'message_reply' ||
        message.type === 'pages_messaging' ||
        (message.body && typeof message.body === 'string');

      if (!isMessage) return;

      try {
        const env = this._normalizeInbound(message);
        if (env) {
          log.info('facebook inbound enqueued to bridge', {
            mid: env.external_message_id,
            from: env.sender.external_id,
            thread: env.metadata.thread_id,
          });
          this.emit('inbound', env);
        }
      } catch (e) {
        log.error('facebook inbound normalize failed', { error: e.message });
      }
    };

    const listenFn = this.api.listenMqtt ? this.api.listenMqtt.bind(this.api)
      : this.api.listen.bind(this.api);

    try {
      this._stopListening = listenFn(onEvent);
    } catch (e) {
      if (this.api.listen) {
        this._stopListening = this.api.listen(onEvent);
      }
    }
  }

  _normalizeInbound(m) {
    const senderId = normalizeId(m.senderID || m.from || m.author);
    if (!senderId) return null;
    const mid = String(m.messageID || m.id || '');
    if (!mid) return null;

    const part = extractText(m);
    const ts = m.timestamp
      ? new Date(Number(m.timestamp)).toISOString()
      : new Date().toISOString();

    return {
      channel: 'facebook',
      event_type: 'message.received',
      external_message_id: mid,
      account_id: 'primary',
      sender: {
        external_id: senderId,
        name: String(m.senderName || ''),
      },
      timestamp: ts,
      message: {
        type: 'text',
        text: part.text || '',
      },
      metadata: {
        transport: 'private',
        thread_id: String(m.threadID || senderId),
      },
    };
  }

  async disconnect() {
    this._expectDisconnect = true;
    if (this._stopListening && typeof this._stopListening === 'function') {
      try { this._stopListening(); } catch { /* best effort */ }
      this._stopListening = null;
    }
    if (this.api && typeof this.api.logout === 'function') {
      try { await new Promise(r => this.api.logout(r)); } catch { /* best effort */ }
    }
    this.api = null;
    this.emit('status', 'DISCONNECTED');
  }

  _requireApi() {
    if (!this.api) {
      const err = new BridgeError('facebook session not connected', 'auth_required', 401);
      throw err;
    }
    return this.api;
  }

  // ---- outbound surface (AmanCode-facing) -------------------------------

  async sendText({ to, text, replyTo }) {
    if (this.shadow) return this._shadowHold('sendText', { to, text });
    const api = this._requireApi();
    const threadId = normalizeId(to);
    if (!threadId) throw new BridgeError('empty recipient thread id', 'invalid_request', 400);

    const msgObj = { body: String(text || '') };
    const replyMid = replyTo ? String(replyTo) : undefined;

    try {
      let info;
      if (typeof api.sendMessage === 'function') {
        info = await new Promise((resolve, reject) => {
          let resolved = false;
          const timer = setTimeout(
            () => { if (!resolved) { resolved = true; reject(new Error('sendMessage timed out (30s)')); } }, 30000);
          const done = (err, val) => {
            if (!resolved) {
              resolved = true;
              clearTimeout(timer);
              if (err) reject(err);
              else resolve(val);
            }
          };
          try {
            const res = api.sendMessage(msgObj, threadId, (err, val) => done(err, val), replyMid);
            if (res && typeof res.then === 'function') {
              res.then((val) => done(null, val)).catch((err) => done(err));
            }
          } catch (e) {
            done(e);
          }
        });
      }
      return {
        external_message_id: info?.messageID || info?.id || `mid-${Date.now()}`,
        to: threadId,
      };
    } catch (err) {
      log.error('facebook sendMessage failed', { error: err.message, to: threadId });
      const cat = /rate|limit/i.test(err.message) ? 'rate_limited' : 'temporary';
      throw new BridgeError(err.message, cat, 500);
    }
  }

  async sendMedia({ to, type, caption }) {
    if (this.shadow) return this._shadowHold('sendMedia', { to, type });
    throw new BridgeError('facebook bridge carries text only in phase 3', 'invalid_request', 400);
  }

  async react({ to, targetMessageId, emoji }) {
    if (this.shadow) return this._shadowHold('react', { to, targetMessageId });
    const api = this._requireApi();
    return new Promise((resolve, reject) => {
      if (typeof api.setMessageReaction !== 'function') {
        return resolve({ external_message_id: String(targetMessageId) });
      }
      api.setMessageReaction(String(emoji || ''), String(targetMessageId), (err) => {
        if (err) return reject(new BridgeError(err.message, 'temporary', 500));
        resolve({ external_message_id: String(targetMessageId) });
      });
    });
  }

  async markRead({ to }) {
    if (this.shadow) return this._shadowHold('markRead', { to });
    const api = this._requireApi();
    const threadId = normalizeId(to);
    return new Promise((resolve) => {
      if (typeof api.markAsRead !== 'function') return resolve({ read: 1 });
      api.markAsRead(threadId, () => resolve({ read: 1 }));
    });
  }

  _shadowHold(op, args) {
    log.info('shadow hold (would_send)', {
      channel: 'facebook', op, to: args.to || undefined,
    });
    return {
      would_send: true,
      shadow: true,
      external_message_id: null,
    };
  }
}

module.exports = { FacebookTransport, normalizeId, extractText };
