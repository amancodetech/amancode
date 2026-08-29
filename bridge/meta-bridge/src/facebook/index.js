'use strict';
// Facebook private transport (facebook-chat-api) — arrives in its own phase.
// Reserved surface only; the server does not register a session for it yet.

class FacebookTransport {
  constructor() {
    throw new Error('facebook transport lands in the facebook phase (spec §20)');
  }
}

module.exports = { FacebookTransport };
