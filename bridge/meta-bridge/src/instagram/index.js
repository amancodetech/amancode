'use strict';
// Instagram realtime transport (instagram-private-api) — arrives in its own
// phase. Reserved surface only; no session registered until then.

class InstagramTransport {
  constructor() {
    throw new Error('instagram transport lands in the instagram phase (spec §21)');
  }
}

module.exports = { InstagramTransport };
