#!/usr/bin/env node
'use strict';
// WhatsApp Business & Personal pairing helper:
// Prints the WhatsApp QR to the terminal for the owner to scan.

const path = require('node:path');
const fs = require('node:fs');
const qrcode = require('qrcode-terminal');

const config = require('../src/core/config');
const { WhatsAppTransport } = require('../src/whatsapp');

// Clean session if --clean is supplied
const sessionDir = path.join(config.dataDir, 'whatsapp_session');
if (process.argv.includes('--clean')) {
  try {
    fs.rmSync(sessionDir, { recursive: true, force: true });
    console.log('[session] cleaned prior session files');
  } catch {}
}

const transport = new WhatsAppTransport(config);
transport.on('status', (s) => {
  console.log(`[status] ${s}`);
  if (s === 'CONNECTED') {
    console.log('\n=============================================');
    console.log('🎉 تم ربط واتساب بزنس بنجاح تام وبشكل دائم!');
    console.log('=============================================\n');
    setTimeout(() => {
      process.exit(0);
    }, 2000);
  }
});

transport.on('qr', (qr) => {
  console.log('\n📱 ================== رمز QR الجديد ==================');
  console.log('امسح الكود من: واتساب للأعمال > الأجهزة المرتبطة > ربط جهاز\n');
  qrcode.generate(qr, { small: true });
  console.log('=======================================================\n');
});

transport.connect().catch((err) => {
  console.error('connect failed:', err.message);
  process.exit(1);
});

setInterval(() => {}, 1 << 30);

