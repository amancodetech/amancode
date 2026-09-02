'use strict';
// SelectorRegistry — central place for all Facebook UI selectors.
// When Facebook changes its UI, update selectors HERE only.

const SELECTORS = {
  // Auth state detection
  auth: {
    loginForm: 'form#login_form',
    loginButton: '[data-testid="royal_login_button"]',
    twoFactorInput: 'input[name="approvals_code"]',
    checkpointContinue: '[data-testid="checkpoint_submit_button"]',
    profilePicture: '[data-testid="bluebar_profile_picture"]',
    navBar: '[role="navigation"]',
  },

  // Messenger UI
  messenger: {
    conversationList: '[role="grid"]',
    conversationItem: '[role="row"]',
    conversationLink: 'a[href*="/messages/t/"]',
    unreadBadge: '[aria-label*="unread"]',
    searchInput: '[aria-label="Search Messenger"]',
    newMessageButton: '[aria-label="New message"]',
  },

  // Message composer
  composer: {
    messageInput: '[role="textbox"][contenteditable="true"][data-lexical-editor="true"]',
    sendButton: '[aria-label="Send"]',
    attachButton: '[aria-label="Attach"]',
    emojiButton: '[aria-label="Open sticker picker"]',
    voiceButton: '[aria-label="Record voice message"]',
  },

  // Message display
  messages: {
    messageContainer: '[role="row"]',
    messageText: '[data-ad-preview="message"]',
    outgoingMessage: '[data-scope="date_column"]',
    incomingMessage: '[data-scope="date_column"]',
    messageTimestamp: 'span[dir="auto"]',
    messageStatus: '[aria-label*="Sent"]',
  },

  // Page inbox (Business Suite)
  pageInbox: {
    inboxContainer: '[role="main"]',
    conversationList: '[role="list"]',
    conversationItem: '[role="listitem"]',
    messageThread: '[role="log"]',
    composer: '[role="textbox"]',
    sendButton: '[aria-label="Send"]',
  },

  // Common
  common: {
    loadingSpinner: '[role="progressbar"]',
    errorMessage: '[role="alert"]',
    modal: '[role="dialog"]',
    closeButton: '[aria-label="Close"]',
    backButton: '[aria-label="Back"]',
  },
};

class SelectorRegistry {
  constructor(overrides = {}) {
    this._selectors = this._deepMerge(SELECTORS, overrides);
  }

  get(category, name) {
    const group = this._selectors[category];
    if (!group) throw new Error(`Unknown selector category: ${category}`);
    const selector = group[name];
    if (!selector) throw new Error(`Unknown selector: ${category}.${name}`);
    return selector;
  }

  getAll(category) {
    return this._selectors[category] || {};
  }

  _deepMerge(target, source) {
    const result = { ...target };
    for (const key of Object.keys(source)) {
      if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
        result[key] = this._deepMerge(result[key] || {}, source[key]);
      } else {
        result[key] = source[key];
      }
    }
    return result;
  }
}

module.exports = { SelectorRegistry, SELECTORS };
