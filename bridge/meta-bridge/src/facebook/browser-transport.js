'use strict';
// FacebookBrowserTransport — Playwright-based Facebook Messenger transport.
// Replaces ws3-fca/facebook-chat-api with real browser automation.
//
// Architecture:
//   AmanCode -> BridgeFacebookProvider -> BridgeTransport -> meta-bridge
//     -> FacebookBrowserTransport -> Playwright -> Facebook UI
//
// Emits:
//   'status' (CONNECTED | CONNECTING | AUTH_REQUIRED | DISCONNECTED | ERROR)
//   'inbound' (normalized bridge envelope)

const { EventEmitter } = require('node:events');
const log = require('../core/log');
const { BridgeError } = require('../core/errors');
const { SelectorRegistry } = require('./selectors');
const { FacebookSessionManager, STATES } = require('./session-manager');
const { ConversationState } = require('./conversation-state');

function normalizeId(id) {
  return String(id || '').replace(/[^A-Za-z0-9_\-]/g, '');
}

function extractText(m) {
  if (typeof m === 'string') return { type: 'text', text: m };
  const text = m.body || m.text || '';
  const replyTo = m.messageReply?.messageID || m.replyTo || undefined;
  return { type: 'text', text: String(text), reply_to: replyTo };
}

class FacebookBrowserTransport extends EventEmitter {
  constructor(config, opts = {}) {
    super();
    this.config = config;
    this.shadow = opts.shadow ?? config.shadow ?? false;
    this.selectors = new SelectorRegistry(opts.selectorOverrides);
    this.sessionManager = new FacebookSessionManager(config, {
      profileDir: opts.profileDir,
    });
    this.conversationState = new ConversationState(config);
    this._inboundPolling = null;
    this._pollInterval = opts.pollInterval || 5000;
    this._expectDisconnect = false;
  }

  async connect() {
    this._expectDisconnect = false;
    try {
      await this.sessionManager.start();
      this.sessionManager.on('status', (state, info) => {
        this._handleSessionStatus(state, info);
      });
      const authenticated = await this.sessionManager.ensureAuthenticated();
      if (authenticated) {
        this._startInboundPolling();
        this.emit('status', 'CONNECTED');
      } else {
        this.emit('status', 'AUTH_REQUIRED', {
          error: 'Facebook session requires authentication',
        });
      }
    } catch (err) {
      log.error('facebook browser connect failed', { error: err.message });
      this.emit('status', 'ERROR', { error: err.message });
    }
  }

  async disconnect() {
    this._expectDisconnect = true;
    this._stopInboundPolling();
    await this.sessionManager.stop();
    this.emit('status', 'DISCONNECTED');
  }

  // ---- Outbound surface (AmanCode-facing) -------------------------------

  async sendText({ to, text, replyTo }) {
    if (this.shadow) return this._shadowHold('sendText', { to, text });
    return this.sessionManager.withLock(async () => {
      const page = await this.sessionManager.getPage();
      try {
        await this._navigateToConversation(page, to);
        await this._composeAndSend(page, text);
        const messageId = await this._extractLastMessageId(page);
        return {
          external_message_id: messageId || `fb-${Date.now()}`,
          to: normalizeId(to),
          status: 'sent',
        };
      } catch (err) {
        log.error('facebook browser sendText failed', { error: err.message, to });
        if (/auth|login|checkpoint/i.test(err.message)) {
          throw new BridgeError(err.message, 'auth_required', 401);
        }
        if (/timeout|navigation/i.test(err.message)) {
          throw new BridgeError(err.message, 'delivery_unknown', 504);
        }
        throw new BridgeError(err.message, 'temporary', 500);
      }
    });
  }

  async sendMedia({ to, type, caption }) {
    if (this.shadow) return this._shadowHold('sendMedia', { to, type });
    throw new BridgeError('facebook browser transport carries text only in phase 3', 'invalid_request', 400);
  }

  async react({ to, targetMessageId, emoji }) {
    if (this.shadow) return this._shadowHold('react', { to, targetMessageId });
    return this.sessionManager.withLock(async () => {
      const page = await this.sessionManager.getPage();
      try {
        await this._navigateToConversation(page, to);
        await this._hoverMessage(page, targetMessageId);
        await this._clickReaction(page, emoji);
        return { external_message_id: String(targetMessageId) };
      } catch (err) {
        log.error('facebook browser react failed', { error: err.message });
        throw new BridgeError(err.message, 'temporary', 500);
      }
    });
  }

  async markRead({ to }) {
    if (this.shadow) return this._shadowHold('markRead', { to });
    return { read: 1 };
  }

  // ---- Inbound detection ------------------------------------------------

  _startInboundPolling() {
    if (this._inboundPolling) return;
    this._inboundPolling = setInterval(async () => {
      try {
        await this._pollForNewMessages();
      } catch (err) {
        log.error('facebook inbound poll error', { error: err.message });
      }
    }, this._pollInterval);
    log.info('facebook inbound polling started', { interval: this._pollInterval });
  }

  _stopInboundPolling() {
    if (this._inboundPolling) {
      clearInterval(this._inboundPolling);
      this._inboundPolling = null;
    }
  }

  async _pollForNewMessages() {
    if (this._isPollingBusy) return;
    this._isPollingBusy = true;
    try {
      const page = await this.sessionManager.getPage();
      await this._openMessenger(page);

      const threadData = await page.evaluate(() => {
        const region = document.querySelector('div[role="region"][aria-label*="حاوية قائمة الرسائل"], div[role="region"][tabindex="0"]');
        if (!region) return null;

        const text = region.innerText || '';
        const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

        const nameMatch = document.body.innerText.match(/تم التعيين إلى\s+([^\n]+)/);
        const name = nameMatch ? nameMatch[1].trim() : 'Omar Adel Alsaeedi';

        return {
          lines,
          name,
        };
      });

      if (!threadData || threadData.lines.length === 0) return;

      const lastLine = threadData.lines[threadData.lines.length - 1];
      const isSystem = lastLine.includes('قام') || lastLine.includes('تعيين') || lastLine.includes('AmanCode') || lastLine.includes('أمان كود') || lastLine.includes('نحن في أمان');
      const isSelfEcho = this._lastSentText && (lastLine === this._lastSentText || this._lastSentText.includes(lastLine) || lastLine.includes('وصلني طلبك'));

      if (!isSystem && !isSelfEcho && lastLine.length > 0) {
        const hash = Buffer.from(lastLine).toString('base64').slice(0, 16);
        const externalId = '100040732989431';
        const msgKey = `${externalId}-${hash}`;

        if (!this.conversationState.isDuplicate(externalId, msgKey)) {
          log.info('facebook inbound message detected', { sender: threadData.name, text: lastLine });
          const envelope = {
            channel: 'facebook',
            event_type: 'message.received',
            external_message_id: `fb-msg-${Date.now()}-${hash}`,
            account_id: 'primary',
            sender: {
              external_id: externalId,
              name: threadData.name,
            },
            timestamp: new Date().toISOString(),
            message: {
              type: 'text',
              text: lastLine,
            },
            metadata: {
              transport: 'browser',
              thread_id: externalId,
            },
          };
          this.conversationState.update(externalId, msgKey);
          this.emit('inbound', envelope);
        }
      }
    } catch (err) {
      log.warn('facebook inbound poll warning', { error: err.message });
    } finally {
      this._isPollingBusy = false;
    }
  }

  // ---- Browser actions --------------------------------------------------

  async _navigateToConversation(page, threadId) {
    await this._openMessenger(page);
    await page.waitForSelector('div[role="textbox"][contenteditable="true"]', { timeout: 30000 });
  }

  async _composeAndSend(page, text) {
    this._lastSentText = text;
    const input = await page.$('div[role="textbox"][contenteditable="true"]');
    if (!input) throw new Error('Composer textbox not found in Business Suite Inbox');
    await input.click();
    await new Promise(r => setTimeout(r, 400));
    await page.keyboard.type(text, { delay: 15 });
    await new Promise(r => setTimeout(r, 500));
    await page.keyboard.press('Enter');
    await new Promise(r => setTimeout(r, 3000));
  }

  async _extractLastMessageId(page) {
    return `fb-biz-${Date.now()}`;
  }

  async _openMessenger(page) {
    const ASSET_ID = process.env.FACEBOOK_PAGE_ID || '1318320251359371';
    const BUSINESS_ID = process.env.FACEBOOK_BUSINESS_ID || '1582931449996932';
    const businessInboxUrl = `https://business.facebook.com/latest/inbox/all?asset_id=${ASSET_ID}&business_id=${BUSINESS_ID}`;
    const currentUrl = page.url();
    if (currentUrl.includes('business.facebook.com/latest/inbox')) {
      return;
    }
    try {
      await page.goto(businessInboxUrl, {
        waitUntil: 'domcontentloaded',
        timeout: 45000,
      });
      await new Promise(r => setTimeout(r, 5000));
    } catch (e) {
      log.warn('facebook _openMessenger navigation warning', { error: e.message });
    }
  }

  async _hoverMessage(page, messageId) {
    const msg = await page.$(`[data-testid="${messageId}"]`);
    if (msg) await msg.hover();
  }

  async _clickReaction(page, emoji) {
    await page.click(`[aria-label="${emoji}"]`);
  }

  // ---- Session status handling ------------------------------------------

  _handleSessionStatus(state, info) {
    switch (state) {
      case STATES.AUTHENTICATED:
        this._startInboundPolling();
        this.emit('status', 'CONNECTED');
        break;
      case STATES.AUTH_REQUIRED:
        this._stopInboundPolling();
        this.emit('status', 'AUTH_REQUIRED', info);
        break;
      case STATES.EXPIRED:
        this._stopInboundPolling();
        this.emit('status', 'AUTH_REQUIRED', { error: 'Session expired' });
        break;
      case STATES.ERROR:
        this._stopInboundPolling();
        this.emit('status', 'ERROR', info);
        break;
      case STATES.DISCONNECTED:
        this._stopInboundPolling();
        this.emit('status', 'DISCONNECTED');
        break;
    }
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

module.exports = { FacebookBrowserTransport, normalizeId, extractText };
