#!/usr/bin/env node
'use strict';
// Pairing via NUMERIC CODE (no QR): pass the NEW WhatsApp number in E164
// digits, e.g.:  node scripts/pair-code.js 201234567890
//
// WhatsApp → Linked devices → Link a device → "Link with phone number instead"
// → enter the printed 8-char code. Session persists (ONE-TIME pairing).
//
// The pairing code is requested ONLY when WhatsApp signals the registration
// window is open (the same moment it would show a QR) — requesting earlier
// causes an immediate server-side logout.

const fs = require('node:fs');
const path = require('node:path');

const phone = (process.argv[2] || '').replace(/\D/g, '');
if (!phone || phone.length < 8) {
  console.error('usage: node scripts/pair-code.js <E164 digits, e.g. 201234567890>');
  process.exit(1);
}

const LOG = path.join(__dirname, '..', 'pair-status.log');

function say(msg) {
  const line = `${new Date().toISOString()} ${msg}`;
  console.log(line);
  fs.appendFileSync(LOG, line + '\n');
}

const config = require('../src/core/config');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  Browsers,
} = require('@whiskeysockets/baileys');

const sessionDir = path.join(config.dataDir, 'whatsapp_session');

function wipeSession(reason) {
  fs.rmSync(sessionDir, { recursive: true, force: true });
  say(`[session] wiped (${reason}) — fresh state on next connect`);
}

let sock = null;
let pairingRequested = false;

// Wipe old failed attempts to guarantee clean pairing state
wipeSession('fresh pairing request');

async function connect() {
  pairingRequested = false;
  fs.mkdirSync(sessionDir, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(sessionDir);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: false,
    // Web browser identity is required for phone number pairing codes
    browser: Browsers.ubuntu('Chrome'),
    syncFullHistory: false,
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
    defaultQueryTimeoutMs: 60_000,
    connectTimeoutMs: 60_000,
    keepAliveIntervalMs: 30_000,
    retryRequestDelayMs: 500,
    getMessage: async () => ({ conversation: '' }),
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr, isNewLogin } = update;
    say(`[event] connection.update: ${JSON.stringify({ connection, isNewLogin, qr: !!qr, error: lastDisconnect?.error?.message, statusCode: lastDisconnect?.error?.output?.statusCode })}`);

    if (qr && !pairingRequested && !sock.authState.creds.registered) {
      pairingRequested = true;
      try {
        const code = await sock.requestPairingCode(phone);
        const pretty = code?.match(/.{1,4}/g)?.join('-') || code;
        say(`\n=================================================`);
        say(`🔑 CODE: ${pretty} (for +${phone})`);
        say(`=================================================\n`);
      } catch (err) {
        say(`[pair-code] request failed: ${err.message}`);
      }
    }

    if (connection === 'open') {
      say('[pair] 🎉 CONNECTED — session saved, pairing complete!');
      say(`[pair] logged in as: +${sock.user?.id?.split(':')[0]}`);
    } else if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      const err = lastDisconnect?.error;
      say(`[pair] connection closed: code=${code}, error=${err?.message || err}`);
    }
  });

  sock.ev.on('creds.update', () => {
    say('[creds] credentials updated/saved');
  });
}

say(`[boot] pairing-code flow for +${phone} …`);
connect().catch((err) => {
  say(`[boot] connect failed: ${err.message}`);
  process.exit(1);
});

setInterval(() => {}, 1 << 30);
