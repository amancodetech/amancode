'use strict';
// FacebookSessionManager — manages persistent Playwright browser sessions.
// One profile, one active browser context, one exclusive operation.

const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const log = require('../core/log');

const STATES = {
  DISCONNECTED: 'DISCONNECTED',
  STARTING: 'STARTING',
  AUTH_REQUIRED: 'AUTH_REQUIRED',
  AUTHENTICATED: 'AUTHENTICATED',
  EXPIRED: 'EXPIRED',
  ERROR: 'ERROR',
};

class FacebookSessionManager extends EventEmitter {
  constructor(config, opts = {}) {
    super();
    this.config = config;
    this.profileDir = opts.profileDir ||
      path.join(config.dataDir, 'facebook_browser_profile');
    this.state = STATES.DISCONNECTED;
    this.browser = null;
    this.context = null;
    this.page = null;
    this._lock = false;
    this._lockQueue = [];
    this._lastActivity = null;
    this._lastError = null;
    this._stateHistory = [];
  }

  async start() {
    if (this.state === STATES.STARTING) return;
    this._setState(STATES.STARTING);
    fs.mkdirSync(this.profileDir, { recursive: true });
    try {
      const { chromium } = require('playwright-core');
      this.context = await chromium.launchPersistentContext(this.profileDir, {
        headless: true,
        channel: undefined,
        executablePath: this.config.browserPath || '/usr/bin/google-chrome',
        viewport: { width: 1280, height: 900 },
        args: ['--disable-blink-features=AutomationControlled', '--lang=en', '--no-sandbox'],
      });
      this.browser = this.context;
      this.page = this.context.pages()[0] || await this.context.newPage();
      log.info('facebook browser started', { profile: this.profileDir });
    } catch (err) {
      this._setState(STATES.ERROR, err.message);
      throw err;
    }
  }

  async stop() {
    if (this.browser) {
      try { await this.browser.close(); } catch { /* best effort */ }
      this.browser = null;
      this.context = null;
      this.page = null;
    }
    this._setState(STATES.DISCONNECTED);
    this._releaseLock();
  }

  async ensureAuthenticated() {
    if (this.state === STATES.AUTHENTICATED) return true;
    if (!this.browser) await this.start();

    // Inject appstate cookies if available
    const appStateFile = path.join(this.config.dataDir, 'facebook_session', 'appstate.json');
    if (fs.existsSync(appStateFile)) {
      try {
        const appState = JSON.parse(fs.readFileSync(appStateFile, 'utf8'));
        const browserCookies = appState.map(c => ({
          name: c.key,
          value: c.value,
          domain: '.' + (c.domain || 'facebook.com').replace(/^\./, ''),
          path: c.path || '/',
        }));
        await this.context.addCookies(browserCookies);
        log.info('facebook injected appstate cookies', { count: browserCookies.length });
      } catch (e) {
        log.error('facebook cookie injection failed', { error: e.message });
      }
    }

    try {
      await this.page.goto('https://business.facebook.com/', {
        waitUntil: 'domcontentloaded',
        timeout: 60000,
      });
    } catch (e) {
      log.warn('facebook ensureAuthenticated navigation failed, trying messenger', { error: e.message });
      try {
        await this.page.goto('https://www.messenger.com/', {
          waitUntil: 'domcontentloaded',
          timeout: 30000,
        });
      } catch (e2) {
        log.error('facebook ensureAuthenticated all URLs failed', { error: e2.message });
      }
    }

    const cookies = await this.context.cookies('https://www.facebook.com');
    const businessCookies = await this.context.cookies('https://business.facebook.com');
    const allCookies = [...cookies, ...businessCookies];
    if (allCookies.some(c => c.name === 'c_user' && c.value)) {
      this._setState(STATES.AUTHENTICATED);
      this._lastActivity = new Date().toISOString();
      return true;
    }
    this._setState(STATES.AUTH_REQUIRED);
    return false;
  }

  async getPage() {
    if (!this.browser || !this.context) {
      await this.start();
    }
    if (!this.page || this.page.isClosed()) {
      this.page = this.context.pages()[0] || await this.context.newPage();
    }
    if (this.state !== STATES.AUTHENTICATED) {
      const ok = await this.ensureAuthenticated();
      if (!ok) throw new Error('Facebook session not authenticated');
    }
    return this.page;
  }

  async withLock(fn) {
    if (this._lock) {
      await new Promise(resolve => this._lockQueue.push(resolve));
    }
    this._lock = true;
    try {
      return await fn();
    } finally {
      this._lock = false;
      if (this._lockQueue.length > 0) {
        this._lockQueue.shift()();
      }
    }
  }

  health() {
    return {
      channel: 'facebook',
      state: this.state,
      profile: this.profileDir,
      last_activity: this._lastActivity,
      last_error: this._lastError,
      browser_running: !!this.browser,
      state_history: this._stateHistory.slice(-5),
    };
  }

  resetContext() {
    this._setState(STATES.DISCONNECTED);
    this._lastError = null;
  }

  _setState(state, error = null) {
    const prev = this.state;
    this.state = state;
    this._lastError = error;
    this._stateHistory.push({
      from: prev,
      to: state,
      timestamp: new Date().toISOString(),
      error,
    });
    if (this._stateHistory.length > 50) {
      this._stateHistory = this._stateHistory.slice(-50);
    }
    this.emit('status', state, { error });
    log.info('facebook session state', { from: prev, to: state, error });
  }

  _releaseLock() {
    this._lock = false;
    while (this._lockQueue.length > 0) {
      this._lockQueue.shift()();
    }
  }
}

module.exports = { FacebookSessionManager, STATES };
