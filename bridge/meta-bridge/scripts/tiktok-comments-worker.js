'use strict';
/**
 * TikTok Studio Comments & Moderation Worker
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const SESSION_FILE = path.join(__dirname, '../../../bridge_data/tiktok_session/session.json');

async function main() {
  console.log('====================================================');
  console.log('  TikTok Studio Auto-Comment & Moderation Worker    ');
  console.log('====================================================\n');

  if (!fs.existsSync(SESSION_FILE)) {
    console.error('❌ TikTok session missing at', SESSION_FILE);
    process.exit(1);
  }

  const sessionData = JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8'));

  const browser = await puppeteer.launch({
    executablePath: fs.existsSync('/snap/bin/brave') ? '/snap/bin/brave' : undefined,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--lang=ar,en',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 900 });

    const client = await page.target().createCDPSession();
    await client.send('Network.setCookies', {
      cookies: (sessionData.cookies || []).map(c => ({
        name: c.key,
        value: c.value,
        domain: '.' + (c.domain || 'tiktok.com').replace(/^\./, ''),
        path: c.path || '/',
      })),
    });

    const commentsUrl = 'https://www.tiktok.com/tiktokstudio/comment';
    console.log('🌐 Navigating to TikTok Studio comments:', commentsUrl);
    await page.goto(commentsUrl, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 6000));

    console.log('Current URL:', page.url());
    console.log('Page Title:', await page.title());

    console.log('✅ TikTok comments check completed.');
    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('❌ Error checking TikTok comments:', err.message);
    try { await browser.close(); } catch {}
    process.exit(1);
  }
}

main();
