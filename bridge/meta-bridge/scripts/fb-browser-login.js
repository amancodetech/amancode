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
      '--dns-result-order=ipv4first',
    ],
  };
  try {
    browser = await puppeteer.launch(launchOptions);
  } catch (err) {
    console.error(`\n❌ Failed to launch Chrome: ${err.message}`);
    console.log('💡 Note: You must be running in a desktop environment with GUI display.');
    process.exit(1);
  }

  const defaultBusinessUrl = 'https://business.facebook.com/latest/inbox/all?asset_id=1318320251359371&business_id=1582931449996932';
  const targetUrl = process.argv[2] || process.env.FB_LOGIN_URL || defaultBusinessUrl;
  console.log(`🌐 Navigating directly to Meta Business Suite Inbox:\n   ${targetUrl}\n`);

  const page = (await browser.pages())[0] || (await browser.newPage());
  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  } catch (err) {
    console.log(`⚠️ Navigation note: ${err.message}. You can navigate manually in the opened Chrome window.`);
  }

  const readline = require('node:readline');
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  console.log('====================================================');
  console.log('🌐 Meta Business Suite Inbox is OPEN in Chrome!');
  console.log('👉 1. Log in to your Facebook / Business account.');
  console.log('👉 2. Make sure you are inside the AmanCode Business Inbox:');
  console.log('      (Page Asset ID: 1318320251359371 | Business ID: 1582931449996932)');
  console.log('👉 3. When you see your conversations, press [ENTER] here in the terminal:');
  console.log('====================================================\n');

  rl.question('👉 Press [ENTER] when ready to capture and save the Business session: ', async () => {
    try {
      const client = await page.target().createCDPSession();
      const { cookies: allCookies } = await client.send('Network.getAllCookies');

      const cUser = allCookies.find(c => c.name === 'c_user');
      const iUser = allCookies.find(c => c.name === 'i_user');
      const xs = allCookies.find(c => c.name === 'xs');

      const activeId = iUser?.value || cUser?.value;

      if (!activeId || !xs) {
        console.error('\n❌ Could not find active login cookies (c_user/i_user/xs). Please make sure you are logged in.');
        try { await browser.close(); } catch {}
        process.exit(1);
      }

      const appState = allCookies.map(c => ({
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

      const metaInfo = {
        page_id: '1318320251359371',
        business_id: '1582931449996932',
        asset_id: '1318320251359371',
        active_user_id: activeId,
        inbox_url: defaultBusinessUrl,
        captured_at: new Date().toISOString(),
      };
      fs.writeFileSync(path.join(sessionDir, 'business_meta.json'), JSON.stringify(metaInfo, null, 2), 'utf8');

      console.log(`\n🎉 Logged in successfully! Captured ${appState.length} cookies across domains.`);
      console.log(`🏢 Business Account ID: 1582931449996932`);
      console.log(`📄 Page Asset ID: 1318320251359371 (AmanCode)`);
      console.log(`🆔 Active ID: ${activeId} ${iUser ? '(Page Profile)' : '(User Profile)'}`);
      console.log(`💾 AppState saved to: ${appStateFile}`);

      await browser.close();
      console.log('\n✅ Meta Business Suite session is ready! Restarting meta-bridge...');
      process.exit(0);
    } catch (e) {
      console.error('\n❌ Error capturing session:', e.message);
      try { await browser.close(); } catch {}
      process.exit(1);
    }
  });
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
