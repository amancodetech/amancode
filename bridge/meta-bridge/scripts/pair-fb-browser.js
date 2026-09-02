#!/usr/bin/env node
'use strict';
// Facebook pairing via a REAL BROWSER (Playwright + system Chrome).
//
//   node scripts/pair-fb-browser.js
//
// A Chrome window opens on facebook.com — YOU log in manually (credentials,
// SMS 2FA code, checkpoint approvals — all natural, real fingerprint).
// The script waits until you are logged in, then harvests the session
// cookies → bridge_data/facebook_session/appstate.json → verifies with the
// bridge driver. Credentials NEVER touch any script or log.

const fs = require('node:fs');
const path = require('node:path');

const config = require('../src/core/config');
const sessionDir = path.join(config.dataDir, 'facebook_session');
const appstateFile = path.join(sessionDir, 'appstate.json');

function loadDriver() {
  for (const name of ['ws3-fca', 'facebook-chat-api',
    '@xaviabot/fca-unofficial']) {
    try {
      const mod = require(name);
      return { name, login: mod.login || mod.default || mod };
    } catch { /* next */ }
  }
  console.error('no facebook driver installed');
  process.exit(1);
}

async function main() {
  const { chromium } = require('playwright-core');
  const userDataDir = path.join(config.dataDir, 'fb_browser_profile');
  fs.mkdirSync(userDataDir, { recursive: true });

  console.log('=== Facebook pairing via real browser ===');
  console.log('A Chrome window will open. Log in MANUALLY:');
  console.log('  → credentials, SMS 2FA code, any checkpoint — handle it all');
  console.log('    inside the window like a normal human login.\n');

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    channel: undefined,
    executablePath: '/snap/bin/brave',
    viewport: { width: 1280, height: 900 },
    args: ['--disable-blink-features=AutomationControlled', '--lang=en'],
  });
  const page = context.pages()[0] || await context.newPage();
  await page.goto('https://www.facebook.com/login/', {
    waitUntil: 'domcontentloaded', timeout: 60000,
  });

  // wait until c_user cookie exists = logged in (poll every 3s, up to 10 min)
  console.log('waiting for login… (you have 10 minutes)');
  let loggedIn = false;
  for (let i = 0; i < 200; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    const cookies = await context.cookies('https://www.facebook.com');
    if (cookies.some((c) => c.name === 'c_user' && c.value)) {
      loggedIn = true;
      break;
    }
  }
  if (!loggedIn) {
    console.error('timed out — no login detected in 10 minutes');
    await context.close();
    process.exit(1);
  }

  // give facebook a few seconds to settle post-login cookies
  await page.goto('https://www.facebook.com/', {
    waitUntil: 'domcontentloaded', timeout: 60000,
  }).catch(() => {});
  await new Promise((r) => setTimeout(r, 5000));

  const cookies = await context.cookies('https://www.facebook.com');
  const now = new Date().toISOString();
  const appState = cookies.map((c) => ({
    key: c.name,
    value: c.value,
    domain: c.domain.startsWith('.') ? c.domain : `.${c.domain.replace(/^\./, '')}`,
    path: c.path || '/',
    hostOnly: c.hostOnly,
    creation: now,
    lastAccessed: now,
  }));
  await context.close();

  const cUser = (appState.find((c) => c.key === 'c_user') || {}).value;
  console.log(`\n✓ login harvested (user: ${cUser}, ${appState.length} cookies)`);

  fs.mkdirSync(sessionDir, { recursive: true });
  fs.writeFileSync(appstateFile, JSON.stringify(appState, null, 2));
  console.log(`✓ appstate saved → ${appstateFile}`);

  // verify through the SAME driver the bridge uses
  const { login } = loadDriver();
  await new Promise((resolve) => {
    login({ appState }, { logLevel: 'silent' }, (err, api) => {
      if (err) {
        console.error('⚠ driver verify FAILED (session may still be flagged):',
          typeof err.error === 'object' ? JSON.stringify(err.error)
            : (err.error || err.message));
        process.exit(1);
      }
      console.log('✓ verified by bridge driver — userID:',
        api.getCurrentUserID());
      try { api.stop(); } catch { /* noop */ }
      resolve();
    });
  });
  console.log('\nNEXT: systemctl --user restart meta-bridge');
}

main().catch((err) => {
  console.error('pairing failed:', err.message);
  process.exit(1);
});
