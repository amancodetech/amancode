#!/usr/bin/env node
'use strict';

// Interactive Instagram Login Script to generate session.json
// Usage: node scripts/ig-login.js

const readline = require('node:readline');
const fs = require('node:fs');
const path = require('node:path');
const { IgApiClient, IgCheckpointError, IgLoginTwoFactorRequiredError } = require('instagram-private-api');

const dataDir = process.env.BRIDGE_DATA_DIR ||
  path.join(__dirname, '..', '..', '..', 'bridge_data');
const sessionDir = path.join(dataDir, 'instagram_session');
const sessionFile = path.join(sessionDir, 'session.json');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

function ask(q) {
  return new Promise(resolve => rl.question(q, resolve));
}

async function saveSession(ig, username) {
  const cookies = await ig.state.serializeCookieJar();
  const state = {
    username,
    deviceString: ig.state.deviceString,
    deviceId: ig.state.deviceId,
    cookies,
    savedAt: new Date().toISOString(),
  };
  fs.mkdirSync(sessionDir, { recursive: true });
  fs.writeFileSync(sessionFile, JSON.stringify(state, null, 2), 'utf8');
  console.log(`\n✅ Instagram login successful!`);
  console.log(`💾 Session saved to: ${sessionFile}`);
  console.log('\n🚀 You can now restart the bridge service:');
  console.log('   systemctl --user restart meta-bridge.service\n');
}

async function main() {
  console.log('====================================================');
  console.log('  Instagram DM Local Bridge — Session Login         ');
  console.log('====================================================\n');

  const username = (await ask('👤 Instagram Username: ')).trim();
  const password = (await ask('🔑 Instagram Password: ')).trim();

  if (!username || !password) {
    console.error('❌ Username and password are required.');
    rl.close();
    process.exit(1);
  }

  console.log('\n⏳ Authenticating with Instagram...');
  const ig = new IgApiClient();
  ig.state.generateDevice(username);

  try {
    const user = await ig.account.login(username, password);
    await saveSession(ig, username);
    rl.close();
    process.exit(0);
  } catch (err) {
    if (err instanceof IgLoginTwoFactorRequiredError) {
      console.log('\n🛡️ Two-Factor Authentication (2FA) is required.');
      const twoFactorInfo = err.response.body.two_factor_info;
      const code = (await ask('📲 Enter 2FA SMS/Authenticator Code: ')).trim();
      try {
        await ig.account.twoFactorLogin({
          username,
          verificationCode: code,
          twoFactorIdentifier: twoFactorInfo.two_factor_identifier,
          verificationMethod: twoFactorInfo.totp_two_factor_on ? '1' : '0',
          trustThisDevice: '1',
        });
        await saveSession(ig, username);
        rl.close();
        process.exit(0);
      } catch (twoFactorErr) {
        console.error(`❌ 2FA verification failed: ${twoFactorErr.message}`);
        rl.close();
        process.exit(1);
      }
    } else if (err instanceof IgCheckpointError) {
      console.log('\n⚠️ Instagram Checkpoint / Challenge triggered.');
      console.log('Please approve the login request on your Instagram mobile app or email.');
      await ig.challenge.auto(true);
      const code = (await ask('📲 Enter Challenge Code sent to SMS/Email: ')).trim();
      try {
        await ig.challenge.sendSecurityCode(code);
        await saveSession(ig, username);
        rl.close();
        process.exit(0);
      } catch (challengeErr) {
        console.error(`❌ Challenge resolution failed: ${challengeErr.message}`);
        rl.close();
        process.exit(1);
      }
    } else {
      console.error(`\n❌ Instagram login failed: ${err.message}`);
      rl.close();
      process.exit(1);
    }
  }
}

main().catch(err => {
  console.error(err);
  rl.close();
  process.exit(1);
});
