#!/usr/bin/env node
'use strict';
// LIVE pairing helper for WhatsApp & WhatsApp Business:
// 1. Prints fresh ASCII QR to terminal
// 2. Writes qr.png to disk
// 3. Serves live web viewer at http://localhost:8766

const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
const QRCode = require('qrcode');
const qrcodeTerminal = require('qrcode-terminal');

const config = require('../src/core/config');
const { WhatsAppTransport } = require('../src/whatsapp');

const QR_PATH = path.join(__dirname, '..', 'qr.png');
const HTML_PATH = path.join(__dirname, '..', 'qr-live.html');
const LOG = path.join(__dirname, '..', 'qr-status.log');

function say(msg) {
  const line = `${new Date().toISOString()} ${msg}`;
  console.log(line);
  try { fs.appendFileSync(LOG, line + '\n'); } catch {}
}

// Ensure clean session on fresh pair
const sessionDir = path.join(config.dataDir, 'whatsapp_session');
if (process.argv.includes('--clean')) {
  try {
    fs.rmSync(sessionDir, { recursive: true, force: true });
    say('[session] cleaned prior session files');
  } catch {}
}

// Simple HTTP server for live browser viewing
const HTTP_PORT = 8766;
const webServer = http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  if (url === '/qr.png') {
    if (fs.existsSync(QR_PATH)) {
      res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'no-cache' });
      fs.createReadStream(QR_PATH).pipe(res);
      return;
    }
    res.writeHead(404);
    res.end();
    return;
  }
  if (fs.existsSync(HTML_PATH)) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    fs.createReadStream(HTML_PATH).pipe(res);
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end('<h1>جاري توليد رمز الـ QR... يرجى تحديث الصفحة بعد ثوانٍ</h1>');
});

webServer.listen(HTTP_PORT, '127.0.0.1', () => {
  say(`[web] 🌐 يمكنك فتح رمز QR في المتصفح أيضاً على: http://localhost:${HTTP_PORT}`);
});

const transport = new WhatsAppTransport(config);

transport.on('status', (s) => {
  say(`[status] ${s}`);
  if (s === 'CONNECTED') {
    console.log('\n=============================================');
    console.log('🎉 تم ربط واتساب بزنس بنجاح تام وبشكل دائم!');
    console.log('=============================================\n');
    setTimeout(() => {
      process.exit(0);
    }, 2000);
  }
});

transport.on('qr', async (qr) => {
  try {
    await QRCode.toFile(QR_PATH, qr, { width: 512, margin: 2 });
    say(`[qr] NEW QR written → ${QR_PATH}`);
  } catch (err) {
    say(`[qr] render failed: ${err.message}`);
  }

  console.log('\n📱 ================== رمز QR الجديد ==================');
  console.log('امسح الكود من: واتساب للأعمال > الأجهزة المرتبطة > ربط جهاز\n');
  qrcodeTerminal.generate(qr, { small: true });
  console.log('=======================================================\n');
});

say('[boot] starting WhatsApp Business pairing listener…');
transport.connect().catch((err) => {
  say(`[boot] connect failed: ${err.message}`);
  process.exit(1);
});

setInterval(() => {}, 1 << 30);

