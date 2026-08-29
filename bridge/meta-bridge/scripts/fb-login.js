#!/usr/bin/env node
'use strict';

// Interactive Facebook Login Script to generate appstate.json
// Usage: node scripts/fb-login.js

const readline = require('node:readline');
const fs = require('node:fs');
const path = require('node:path');

const dataDir = process.env.BRIDGE_DATA_DIR ||
  path.join(__dirname, '..', '..', '..', 'bridge_data');
const sessionDir = path.join(dataDir, 'facebook_session');
const appStateFile = path.join(sessionDir, 'appstate.json');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

function ask(q) {
  return new Promise(resolve => rl.question(q, resolve));
}

async function main() {
  console.log('====================================================');
  console.log('  Facebook Messenger Local Bridge — Session Login   ');
  console.log('====================================================\n');

  const email = (await ask('📧 Facebook Email / Phone: ')).trim();
  const password = (await ask('🔑 Facebook Password: ')).trim();
  const code2FA = (await ask('🛡️ 2FA Code (press Enter if not enabled): ')).trim();

  rl.close();

  if (!email || !password) {
    console.error('❌ Email and password are required.');
    process.exit(1);
  }

  console.log('\n⏳ Authenticating with Facebook...');

  let loginFn;
  try {
    const mod = require('ws3-fca');
    loginFn = mod.login || mod;
  } catch {
    try {
      const mod = require('facebook-chat-api');
      loginFn = mod.login || mod;
    } catch {
      console.error('❌ ws3-fca library not found.');
      process.exit(1);
    }
  }

  const credentials = { email, password };
  if (code2FA) credentials.twoFactorCode = code2FA;

  loginFn(credentials, { logLevel: 'silent' }, (err, api) => {
    if (err) {
      console.error(`\n❌ Facebook login failed: ${err.error || err.message || JSON.stringify(err)}`);
      console.log('\n💡 Tip: If you have 2FA enabled, enter the OTP code, or alternatively use an AppState JSON exported from your browser.');
      process.exit(1);
    }

    try {
      const appState = api.getAppState();
      fs.mkdirSync(sessionDir, { recursive: true });
      fs.writeFileSync(appStateFile, JSON.stringify(appState, null, 2), 'utf8');
      console.log(`\n✅ Facebook login successful!`);
      console.log(`💾 AppState saved to: ${appStateFile}`);
      console.log('\n🚀 You can now restart the bridge service:');
      console.log('   systemctl --user restart meta-bridge.service\n');
      process.exit(0);
    } catch (saveErr) {
      console.error(`❌ Failed to save appstate: ${saveErr.message}`);
      process.exit(1);
    }
  });
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
