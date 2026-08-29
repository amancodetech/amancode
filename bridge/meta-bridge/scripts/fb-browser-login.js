#!/usr/bin/env node
'use strict';

// Interactive Facebook Login via Browser Window (Puppeteer)
// Usage: node scripts/fb-browser-login.js

const puppeteer = require('puppeteer');
const fs = require('node:fs');
const path = require('node:path');

const dataDir = process.env.BRIDGE_DATA_DIR ||
  path.join(__dirname, '..', '..', '..', 'bridge_data');
const sessionDir = path.join(dataDir, 'facebook_session');
const appStateFile = path.join(sessionDir, 'appstate.json');

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
  console.log('  Facebook Interactive Browser Login (Chrome)       ');
  console.log('====================================================\n');
  console.log('🌐 Opening Facebook login window in Google Chrome...');
  console.log('👉 Please log in to your Facebook account in the opened browser window.');

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
  await page.goto('https://www.facebook.com/', { waitUntil: 'domcontentloaded' });

  console.log('\n⏳ Waiting for you to complete login in the browser...');

  // Poll for cookies every 2 seconds
  const pollInterval = setInterval(async () => {
    try {
      const url = page.url();
      const cookies = await page.cookies();
      const cUser = cookies.find(c => c.name === 'c_user');
      const xs = cookies.find(c => c.name === 'xs');

      if (cUser && xs && !url.includes('login') && !url.includes('checkpoint') && !url.includes('two_factor')) {
        clearInterval(pollInterval);
        console.log('\n⏳ Finalizing Facebook session cookies (3 seconds)...');
        await new Promise(r => setTimeout(r, 3000));

        const finalCookies = await page.cookies();
        console.log(`\n🎉 Logged in successfully as user ID: ${cUser.value}`);

        const appState = finalCookies.map(c => ({
          key: c.name,
          value: c.value,
          domain: c.domain.replace(/^\./, ''),
          path: c.path,
          hostOnly: !c.domain.startsWith('.'),
          creation: new Date().toISOString(),
          lastAccessed: new Date().toISOString(),
        }));

        fs.mkdirSync(sessionDir, { recursive: true });
        fs.writeFileSync(appStateFile, JSON.stringify(appState, null, 2), 'utf8');
        console.log(`💾 AppState saved to: ${appStateFile}`);

        await browser.close();
        console.log('\n✅ Facebook session is ready! Restarting meta-bridge...');
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
