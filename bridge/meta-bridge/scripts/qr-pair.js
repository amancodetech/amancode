#!/usr/bin/env node
'use strict';
// One-shot pairing helper: prints the WhatsApp QR to the terminal for the
// owner to scan (WhatsApp → Linked devices → Link a device).
// Session credentials persist under BRIDGE_DATA_DIR/whatsapp_session —
// pairing is a ONE-TIME action per number.

const path = require('node:path');
const qrcode = require('qrcode-terminal');

const config = require('../src/core/config');
const { WhatsAppTransport } = require('../src/whatsapp');

const transport = new WhatsAppTransport(config);
transport.on('status', (s) => console.log(`[status] ${s}`));
transport.on('qr', (qr) => {
  console.log('\nScan this QR with the NEW WhatsApp number:\n');
  qrcode.generate(qr, { small: true });
  console.log('\n(re-run this script if the QR expires — ~60s validity)');
});

transport.connect().catch((err) => {
  console.error('connect failed:', err.message);
  process.exit(1);
});

// stay alive until linked; the socket stays open and will report CONNECTED
setInterval(() => {}, 1 << 30);
