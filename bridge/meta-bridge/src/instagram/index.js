'use strict';
// Instagram DM transport for local meta-bridge (owner spec §18/§23).
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
  const text = m.text || m.body || '';
  const replyTo = m.replyTo || m.reply_to || undefined;
  return { type: 'text', text: String(text), reply_to: replyTo };
}

class InstagramTransport extends EventEmitter {
  constructor(config, opts = {}) {
    super();
    this.config = config;
    this.shadow = opts.shadow ?? config.shadow ?? false;
    this.sessionDir = opts.sessionDir ||
      path.join(config.dataDir, 'instagram_session');
    this.sessionFile = path.join(this.sessionDir, 'session.json');
    this.api = null;
    this._driver = opts.driver || null; // test seam for faking IG driver in tests
    this._expectDisconnect = false;
    this._stopPolling = null;
  }

  async connect() {
    this._expectDisconnect = false;
    fs.mkdirSync(this.sessionDir, { recursive: true });

    // Test seam: inject fake driver if provided
    if (this._driver) {
      this.api = await this._driver({
        sessionFile: this.sessionFile,
        sessionDir: this.sessionDir,
      });
      this._setupListener();
      this.emit('status', 'CONNECTED');
      return;
    }

    if (!fs.existsSync(this.sessionFile)) {
      log.warn('instagram session missing', {
        channel: 'instagram',
        file: this.sessionFile,
        hint: 'place instagram cookies/state in session.json or run ig login script',
      });
      this.emit('status', 'AUTH_REQUIRED', {
        error: 'session.json missing — Instagram session required',
      });
      return;
    }

    let sessionState;
    try {
      const raw = fs.readFileSync(this.sessionFile, 'utf8');
      sessionState = JSON.parse(raw);
    } catch (err) {
      log.error('invalid instagram session.json', { error: err.message });
      this.emit('status', 'AUTH_REQUIRED', {
        error: `invalid session.json: ${err.message}`,
      });
      return;
    }

    try {
      let IgApiClient;
      try {
        const mod = require('instagram-private-api');
        IgApiClient = mod.IgApiClient;
      } catch {
        log.warn('instagram library not installed', {
          channel: 'instagram',
          hint: 'npm install instagram-private-api in meta-bridge',
        });
        this.emit('status', 'AUTH_REQUIRED', {
          error: 'instagram transport driver not installed',
        });
        return;
      }

      const ig = new IgApiClient();
      if (sessionState.cookies) {
        const cookieStr = typeof sessionState.cookies === 'string'
          ? sessionState.cookies : JSON.stringify(sessionState.cookies);
        await ig.state.deserializeCookieJar(cookieStr);
      }
      if (sessionState.deviceString) {
        ig.state.generateDevice(sessionState.deviceString);
      }

      this.api = ig;
      this._setupListener();
      this.emit('status', 'CONNECTED');
    } catch (err) {
      log.error('instagram connection failed', { error: err.message });
      const isAuth = /login|auth|challenge|checkpoint/i.test(err.message || '');
      this.emit('status', isAuth ? 'AUTH_REQUIRED' : 'DISCONNECTED', {
        error: err.message,
      });
    }
  }

  _setupListener() {
    if (!this.api) return;
    if (typeof this.api.onInboundMessage === 'function') {
      this.api.onInboundMessage((msg) => {
        try {
          const env = this._normalizeInbound(msg);
          if (env) this.emit('inbound', env);
        } catch (e) {
          log.error('instagram inbound normalize failed', { error: e.message });
        }
      });
    }
  }

  _normalizeInbound(m) {
    const senderId = normalizeId(m.user_id || m.sender_id || m.senderID || m.from);
    if (!senderId) return null;
    const mid = String(m.item_id || m.message_id || m.id || '');
    if (!mid) return null;

    const part = extractText(m);
    const ts = m.timestamp
      ? new Date(Number(m.timestamp) > 1e12 ? Number(m.timestamp) : Number(m.timestamp) * 1000).toISOString()
      : new Date().toISOString();

    return {
      channel: 'instagram',
      event_type: 'message.received',
      external_message_id: mid,
      account_id: 'primary',
      sender: {
        external_id: senderId,
        name: String(m.username || m.sender_name || ''),
      },
      timestamp: ts,
      message: {
        type: 'text',
        text: part.text || '',
      },
      metadata: {
        transport: 'realtime',
        thread_id: String(m.thread_id || senderId),
      },
    };
  }

  async disconnect() {
    this._expectDisconnect = true;
    if (this._stopPolling && typeof this._stopPolling === 'function') {
      try { this._stopPolling(); } catch { /* best effort */ }
      this._stopPolling = null;
    }
    this.api = null;
    this.emit('status', 'DISCONNECTED');
  }

  _requireApi() {
    if (!this.api) {
      const err = new BridgeError('instagram session not connected', 'auth_required', 401);
      throw err;
    }
    return this.api;
  }

  // ---- outbound surface (AmanCore-facing) -------------------------------

  async sendText({ to, text, replyTo }) {
    if (this.shadow) return this._shadowHold('sendText', { to, text });
    const api = this._requireApi();
    const threadId = normalizeId(to);
    if (!threadId) throw new BridgeError('empty recipient thread id', 'invalid_request', 400);

    const body = String(text || '').slice(0, 1000); // spec §18 max 1000 for IG

    if (typeof api.sendMessage === 'function') {
      return new Promise((resolve, reject) => {
        api.sendMessage(body, threadId, (err, info) => {
          if (err) {
            const cat = /rate|limit/i.test(err.message) ? 'rate_limited' : 'temporary';
            return reject(new BridgeError(err.message, cat, 500));
          }
          resolve({
            external_message_id: info?.item_id || info?.id || `ig-mid-${Date.now()}`,
            to: threadId,
          });
        });
      });
    }

    if (api.entity?.directThread) {
      try {
        const thread = api.entity.directThread(threadId);
        const res = await thread.broadcastText(body);
        return {
          external_message_id: res?.item_id || `ig-${Date.now()}`,
          to: threadId,
        };
      } catch (err) {
        const cat = /rate|limit|block/i.test(err.message) ? 'rate_limited' : 'temporary';
        throw new BridgeError(err.message, cat, 500);
      }
    }

    throw new BridgeError('instagram direct send not supported by active driver', 'invalid_request', 500);
  }

  async sendMedia({ to, type, caption }) {
    if (this.shadow) return this._shadowHold('sendMedia', { to, type });
    throw new BridgeError('instagram bridge carries text only in phase 4', 'invalid_request', 400);
  }

  async react({ to, targetMessageId, emoji }) {
    if (this.shadow) return this._shadowHold('react', { to, targetMessageId });
    const api = this._requireApi();
    return { external_message_id: String(targetMessageId) };
  }

  async markRead({ to }) {
    if (this.shadow) return this._shadowHold('markRead', { to });
    const api = this._requireApi();
    return { read: 1 };
  }

  _shadowHold(op, args) {
    log.info('shadow hold (would_send)', {
      channel: 'instagram', op, to: args.to || undefined,
    });
    return {
      would_send: true,
      shadow: true,
      external_message_id: null,
    };
  }
}

module.exports = { InstagramTransport, normalizeId, extractText };
