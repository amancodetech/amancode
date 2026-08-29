#!/usr/bin/env node
'use strict';

// Interactive Instagram Login via Browser Window (Puppeteer)
// Usage: node scripts/ig-browser-login.js

const puppeteer = require('puppeteer');
const fs = require('node:fs');
const path = require('node:path');

const dataDir = process.env.BRIDGE_DATA_DIR ||
  path.join(__dirname, '..', '..', '..', 'bridge_data');
const sessionDir = path.join(dataDir, 'instagram_session');
const sessionFile = path.join(sessionDir, 'session.json');

function findChrome() {
  const cacheDir = path.join(process.env.HOME || '/home/omar', '.cache', 'puppeteer', 'chrome');
  if (fs.existsSync(cacheDir)) {
    for (const entry of fs.readdirSync(cacheDir)) {
      const p = path.join(cacheDir, entry, 'chrome-linux64', 'chrome');
      if (fs.existsSync(p)) return p;
    }
  }
  return undefined;
}

async function main() {
  console.log('====================================================');
  console.log('  Instagram Interactive Browser Login (Chrome)      ');
  console.log('====================================================\n');
  console.log('🌐 Opening Instagram login window in Google Chrome...');
  console.log('👉 Please log in to your Instagram account in the opened browser window.');

  let browser;
  const chromePath = findChrome();
  const launchOptions = {
    headless: false,
    defaultViewport: null,
    executablePath: chromePath,
    args: [
      '--start-maximized',
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
    ],
  };
  try {
    browser = await puppeteer.launch(launchOptions);
  } catch (err) {
    console.error(`\n❌ Failed to launch Chrome: ${err.message}`);
    console.log('💡 Note: You must be running in a desktop environment with GUI display.');
    process.exit(1);
  }

  const page = (await browser.pages())[0] || (await browser.newPage());
  await page.goto('https://www.instagram.com/accounts/login/', { waitUntil: 'domcontentloaded' });

  console.log('\n⏳ Waiting for you to complete login in the browser...');

  const pollInterval = setInterval(async () => {
    try {
      const cookies = await page.cookies();
      const sessionid = cookies.find(c => c.name === 'sessionid');
      const dsUserId = cookies.find(c => c.name === 'ds_user_id');

      if (sessionid && dsUserId) {
        clearInterval(pollInterval);
        console.log(`\n🎉 Logged in successfully as user ID: ${dsUserId.value}`);

        const cookieJarData = {
          cookies: cookies.map(c => ({
            key: c.name,
            value: c.value,
            domain: c.domain.replace(/^\./, ''),
            path: c.path,
            hostOnly: !c.domain.startsWith('.'),
            creation: new Date().toISOString(),
            lastAccessed: new Date().toISOString(),
          })),
        };

        const state = {
          username: dsUserId.value,
          deviceId: `android-${dsUserId.value}`,
          deviceString: `Instagram 269.0.0.18.75 Android (29/10; 480dpi; 1080x2160)`,
          cookies: cookieJarData,
          savedAt: new Date().toISOString(),
        };

        fs.mkdirSync(sessionDir, { recursive: true });
        fs.writeFileSync(sessionFile, JSON.stringify(state, null, 2), 'utf8');
        console.log(`💾 Session saved to: ${sessionFile}`);

        await browser.close();
        console.log('\n✅ Instagram session is ready! Restarting meta-bridge...');
        process.exit(0);
      }
    } catch (e) {
      // ignore
    }
  }, 2000);

  // Timeout after 5 minutes
  setTimeout(async () => {
    clearInterval(pollInterval);
    console.log('\n⏱️ Login timed out after 5 minutes.');
    try { await browser.close(); } catch {}
    process.exit(1);
  }, 300000);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
