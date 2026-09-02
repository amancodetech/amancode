'use strict';
// Error taxonomy mirroring AmanCode's BridgeError categories (spec §43).

const CATEGORIES = Object.freeze([
  'auth_required',      // bridge or upstream session is not authenticated
  'rate_limited',       // upstream told us to back off
  'temporary',          // transient — safe to retry later (probe-class)
  'invalid_request',    // caller bug — never retry
  'not_found',          // unknown id
  'delivery_unknown',   // sent upstream, outcome unknown — NEVER blind-retry
  'permanent',          // upstream refused permanently — never retry
]);

class BridgeError extends Error {
  constructor(message, category, status, details) {
    super(message);
    this.name = 'BridgeError';
    this.category = CATEGORIES.includes(category) ? category : 'permanent';
    this.status = status || statusFor(this.category);
    this.details = details || {};
  }
  toJSON() {
    return { error: this.message, category: this.category, details: this.details };
  }
}

function statusFor(category) {
  switch (category) {
    case 'auth_required': return 401;
    case 'rate_limited': return 429;
    case 'invalid_request': return 400;
    case 'not_found': return 404;
    case 'temporary': return 503;
    case 'delivery_unknown': return 531; // non-standard: outcome unknown
    default: return 500;
  }
}

function statusToCategory(status) {
  if (status === 401 || status === 403) return 'auth_required';
  if (status === 429) return 'rate_limited';
  if (status === 404) return 'not_found';
  if (status === 400 || status === 422) return 'invalid_request';
  if (status === 531) return 'delivery_unknown';
  if (status >= 500) return 'temporary';
  return 'permanent';
}

module.exports = { BridgeError, CATEGORIES, statusFor, statusToCategory };
