'use strict';
// WhatsApp transport over Baileys (pinned). This is the ONLY place in the
// whole system that knows about Baileys internals (owner spec §17/§39).
//
// Exposes the channel-agnostic transport surface consumed by the bridge:
//   connect / disconnect / sendText / sendMedia / react / markRead
// Emits:
//   'status' (CONNECTED|CONNECTING|AUTH_REQUIRED|DISCONNECTED, {error?})
//   'inbound' (normalized bridge envelope)

const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');

const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  downloadMediaMessage,
  Browsers,
} = require('@whiskeysockets/baileys');

const log = require('../core/log');

const JID_SUFFIX = '@s.whatsapp.net';

// Baileys DisconnectReason → session semantics
function classifyDisconnect(code) {
  if (code === DisconnectReason.loggedOut) return 'AUTH_REQUIRED';
  if (code === DisconnectReason.connectionReplaced) return 'DISCONNECTED';
  return 'DISCONNECTED'; // everything else is retryable via backoff
}

// digits-only E164 — identical semantics to the Graph identity (parity!)
function normalizePhone(jid) {
  if (jid === 'status@broadcast' || jid === 'status') return 'status';
  const user = String(jid || '').split('@')[0].split(':')[0];
  return user.replace(/\D/g, '');
}

function toJid(phone, jidMap = null) {
  const raw = String(phone || '').trim();
  if (raw === 'status@broadcast' || raw === 'status' || raw.endsWith('@broadcast') || raw.endsWith('@s.whatsapp.net') || raw.endsWith('@lid') || raw.endsWith('@g.us')) {
    return raw === 'status' ? 'status@broadcast' : raw;
  }
  const digits = raw.replace(/\D/g, '');
  if (!digits) throw new Error('empty recipient phone');
  if (jidMap && jidMap.has(digits)) {
    return jidMap.get(digits);
  }
  return `${digits}${JID_SUFFIX}`;
}

function extractText(m) {
  const msg = m.message || {};
  if (msg.conversation) return { type: 'text', text: msg.conversation };
  if (msg.extendedTextMessage) {
    const text = msg.extendedTextMessage.text || '';
    const replyKey = msg.extendedTextMessage.contextInfo?.stanzaId;
    return { type: 'text', text, reply_to: replyKey || undefined };
  }
  if (msg.imageMessage) return mediaPart(msg.imageMessage, 'image');
  if (msg.videoMessage) return mediaPart(msg.videoMessage, 'video');
  if (msg.audioMessage) return mediaPart(msg.audioMessage, 'audio');
  if (msg.documentMessage) return mediaPart(msg.documentMessage, 'document');
  if (msg.stickerMessage) return { type: 'sticker', text: '' };
  return { type: 'unsupported', text: '' };
}

function mediaPart(part, type) {
  return {
    type,
    text: part.caption || '',
    // media bytes are fetched lazily via download() — envelope carries ref
    media_ref: true,
  };
}

class WhatsAppTransport extends EventEmitter {
  constructor(config, opts = {}) {
    super();
    this.config = config;
    this.shadow = opts.shadow ?? config.shadow ?? false;
    this.sessionDir = opts.sessionDir ||
      path.join(config.dataDir, 'whatsapp_session');
    this.jidMapFile = path.join(this.sessionDir, 'jid_map.json');
    this.jidMap = new Map();
    this._loadJidMap();
    this.sock = null;
    this._credentials = opts.credentials || null; // test seam
    this._version = opts.version || null;          // test seam
    this._expectDisconnect = false;
  }

  _loadJidMap() {
    try {
      if (fs.existsSync(this.jidMapFile)) {
        const data = JSON.parse(fs.readFileSync(this.jidMapFile, 'utf8'));
        for (const [k, v] of Object.entries(data)) {
          this.jidMap.set(k, v);
        }
      }
    } catch (e) {
      log.warn('could not load jid_map', { error: e.message });
    }
  }

  _saveJidMap() {
    try {
      const obj = Object.fromEntries(this.jidMap);
      fs.writeFileSync(this.jidMapFile, JSON.stringify(obj, null, 2), 'utf8');
    } catch (e) {
      log.warn('could not save jid_map', { error: e.message });
    }
  }

  _toJid(phone) {
    return toJid(phone, this.jidMap);
  }

  async connect() {
    this._expectDisconnect = false;
    fs.mkdirSync(this.sessionDir, { recursive: true });
    const { state, saveCreds } = this._credentials
      ? await this._credentials(this.sessionDir)
      : await useMultiFileAuthState(this.sessionDir);
    const { version } = this._version ? { version: this._version }
      : await fetchLatestBaileysVersion();

    this.sock = makeWASocket({
      version,
      auth: state,
      printQRInTerminal: false,
      browser: Browsers.macOS('Desktop'),
      syncFullHistory: false,
      markOnlineOnConnect: false,
      generateHighQualityLinkPreview: false,
      defaultQueryTimeoutMs: 60_000,
      connectTimeoutMs: 60_000,
      keepAliveIntervalMs: 30_000,
      retryRequestDelayMs: 500,
      getMessage: async () => ({ conversation: '' }),
      // SLOW QR rotation: the default (~20s) rotates the noise keypair
      // mid-handshake when the phone is still "logging in" — the pairing
      // then dies and the phone spins forever. 2 minutes per QR is safe.
      qrTimeout: 120_000,
    });

    this.sock.ev.on('creds.update', saveCreds);

    this.sock.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect, qr } = update;
      if (qr) {
        log.warn('whatsapp QR needed', {
          channel: 'whatsapp',
          hint: 'run: npm run qr (bridge/meta-bridge) to pair',
        });
        this.emit('qr', qr);
      }
      if (connection === 'connecting') {
        this.emit('status', 'CONNECTING');
      } else if (connection === 'open') {
        this.emit('status', 'CONNECTED');
      } else if (connection === 'close') {
        const code = lastDisconnect?.error?.output?.statusCode;
        const state = classifyDisconnect(code);
        log.warn('whatsapp connection closed', {
          channel: 'whatsapp', code, next: state,
        });
        if (state === 'AUTH_REQUIRED' || this._expectDisconnect) {
          this.emit('status', state, { error: `closed code=${code}` });
        } else {
          this.emit('status', 'DISCONNECTED', { error: `closed code=${code}` });
          // schedule a fresh socket — Baileys sockets are single-use
          setTimeout(() => {
            if (!this._expectDisconnect) this.connect().catch(() => {});
          }, 3000).unref();
        }
      }
    });

    this.sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return; // notify = new inbound only
      for (const m of messages) {
        try {
          if (m.key?.fromMe) continue;
          const env = this._normalizeInbound(m);
          if (env) this.emit('inbound', env);
        } catch (err) {
          log.error('inbound normalize failed', {
            channel: 'whatsapp', error: err.message,
          });
        }
      }
    });
  }

  _normalizeInbound(m) {
    const rawJid = m.key?.remoteJid;
    const externalId = normalizePhone(rawJid);
    if (!externalId) return null;
    if (rawJid?.endsWith('@g.us') || rawJid === 'status@broadcast') return null; // ignore groups/status@broadcast
    if (!/^\d+$/.test(externalId)) return null;
    const externalMessageId = String(m.key?.id || '');
    if (!externalMessageId) return null;

    if (rawJid) {
      this.jidMap.set(externalId, rawJid);
      this._saveJidMap();
    }

    const part = extractText(m);
    const pushName = String(m.pushName || '');
    const ts = m.messageTimestamp
      ? new Date(Number(m.messageTimestamp) * 1000).toISOString()
      : new Date().toISOString();

    const envelope = {
      channel: 'whatsapp',
      event_type: 'message.received',
      external_message_id: externalMessageId,
      account_id: 'primary',
      sender: { external_id: externalId, name: pushName },
      timestamp: ts,
      message: {
        type: part.type,
        text: part.text || '',
      },
      metadata: {
        transport: 'baileys',
        wa_jid: rawJid,
      },
    };
    if (part.reply_to) {
      envelope.message.reply_to = part.reply_to;
    }
    // media: store a lazy download handle for the API layer
    if (part.media_ref) {
      envelope.message.media = { lazy: true, _ref: m };
    }
    return envelope;
  }

  async download(envelope) {
    const ref = envelope?.message?.media?._ref;
    if (!ref) throw new Error('no media reference on envelope');
    const buffer = await downloadMediaMessage(ref, 'buffer', {});
    return buffer;
  }

  async disconnect() {
    this._expectDisconnect = true;
    if (this.sock) {
      try { this.sock.end(undefined); } catch { /* already closed */ }
      this.sock = null;
    }
    this.emit('status', 'DISCONNECTED');
  }

  _requireSocket() {
    if (!this.sock) {
      const err = new Error('whatsapp session not connected');
      err.category = 'auth_required';
      throw err;
    }
    return this.sock;
  }

  _assertSessionReady() {
    if (!this.sock || this.sock.user === undefined) {
      const err = new Error('whatsapp session not connected');
      err.category = 'auth_required';
      throw err;
    }
  }

  // ---- outbound surface (AmanCode-facing semantics) --------------------

  async sendText({ to, text, replyTo }) {
    if (this.shadow) return this._shadowHold('sendText', { to, text });
    const sock = this._requireSocket();
    const jid = this._toJid(to);
    const content = { text: String(text || '') };
    if (replyTo) content.quoted = await this._quoted(jid, replyTo);
    const result = await sock.sendMessage(jid, content);
    return {
      external_message_id: result?.key?.id,
      to: normalizePhone(jid),
    };
  }

  async sendMedia({ to, type, base64, caption, filename, replyTo }) {
    if (this.shadow) return this._shadowHold('sendMedia', { to, type });
    const sock = this._requireSocket();
    const jid = this._toJid(to);
    const buf = Buffer.from(String(base64 || ''), 'base64');
    if (!buf.length) {
      const err = new Error('empty media payload');
      err.category = 'invalid_request';
      throw err;
    }
    const content = { [type]: buf, caption: caption || undefined,
      fileName: filename || undefined };
    if (replyTo) content.quoted = await this._quoted(jid, replyTo);
    const result = await sock.sendMessage(jid, content);
    return {
      external_message_id: result?.key?.id,
      to: normalizePhone(jid),
    };
  }

  async react({ to, targetMessageId, emoji }) {
    if (this.shadow) return this._shadowHold('react', { to, targetMessageId });
    const sock = this._requireSocket();
    const jid = this._toJid(to);
    await sock.sendMessage(jid, {
      react: { text: String(emoji || ''), key: {
        remoteJid: jid, id: String(targetMessageId), fromMe: false,
        participant: undefined,
      } },
    });
    return { external_message_id: String(targetMessageId) };
  }

  async markRead({ to, messageIds }) {
    if (this.shadow) return this._shadowHold('markRead', { to });
    const sock = this._requireSocket();
    const jid = this._toJid(to);
    const keys = (messageIds || []).map(id => ({
      remoteJid: jid, id: String(id), fromMe: false,
    }));
    await sock.readMessages(keys);
    return { read: keys.length };
  }

  async _quoted(jid, messageId) {
    return { key: { remoteJid: jid, id: String(messageId), fromMe: false } };
  }

  async updateProfilePicture(imagePath) {
    const sock = this._requireSocket();
    const jid = sock.user?.id ? (sock.user.id.split(':')[0] + '@s.whatsapp.net') : null;
    if (!jid) throw new Error('WhatsApp user JID not found');
    return await sock.updateProfilePicture(jid, { url: imagePath });
  }

  _shadowHold(op, args) {
    log.info('shadow hold (would_send)', {
      channel: 'whatsapp', op, to: args.to || undefined,
    });
    return {
      would_send: true,
      shadow: true,
      external_message_id: null,
    };
  }
}

module.exports = { WhatsAppTransport, normalizePhone, toJid, extractText };
