'use strict';
/**
 * TikTok Interactive Browser Login via Google Chrome
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const DATA_DIR = path.join(__dirname, '../../../bridge_data/tiktok_session');
const SESSION_FILE = path.join(DATA_DIR, 'session.json');
const USER_DATA_DIR = path.join(DATA_DIR, 'chrome_profile');

const CHROME_PATH = '/opt/google/chrome/chrome';

async function main() {
  console.log('====================================================');
  console.log('  TikTok Interactive Login (Google Chrome)          ');
  console.log('====================================================\n');
  console.log('🌐 Launching Google Chrome for TikTok login...');
  console.log('👉 Please log in to your TikTok account in Chrome.\n');

  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.mkdirSync(USER_DATA_DIR, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: fs.existsSync(CHROME_PATH) ? CHROME_PATH : undefined,
    headless: false,
    defaultViewport: null,
    userDataDir: USER_DATA_DIR,
    ignoreDefaultArgs: ['--enable-automation'],
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-blink-features=AutomationControlled',
      '--start-maximized',
      '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    ],
  });

  const pages = await browser.pages();
  const page = pages[0] || (await browser.newPage());

  await page.evaluateOnNewDocument(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  });

  const targetUrl = 'https://www.tiktok.com/login';
  console.log('🌐 Navigating to:', targetUrl);
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' }).catch(() => {});

  console.log('\n====================================================');
  console.log('🌐 Google Chrome is OPEN!');
  console.log('👉 1. Log in to your TikTok account.');
  console.log('👉 2. When your profile / TikTok Studio is loaded,');
  console.log('👉 3. Come back to this terminal and press [ENTER].');
  console.log('====================================================\n');

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  await new Promise((resolve) => {
    rl.question('👉 Press [ENTER] when you are logged in to capture the TikTok session: ', () => {
      rl.close();
      resolve();
    });
  });

  console.log('\n⏳ Capturing cookies and session state from Chrome...');
  const client = await page.target().createCDPSession();
  const { cookies } = await client.send('Network.getAllCookies');

  const sessionid = cookies.find(c => c.name === 'sessionid')?.value;

  const sessionData = {
    capturedAt: new Date().toISOString(),
    browser: 'chrome',
    url: page.url(),
    sessionid: sessionid,
    cookies: cookies.map(c => ({
      key: c.name,
      value: c.value,
      domain: c.domain,
      path: c.path,
      expires: c.expires,
      httpOnly: c.httpOnly,
      secure: c.secure,
      sameSite: c.sameSite,
    })),
  };

  fs.writeFileSync(SESSION_FILE, JSON.stringify(sessionData, null, 2), 'utf8');

  console.log(`\n🎉 Logged in successfully! Captured ${cookies.length} cookies.`);
  console.log(`💾 Saved TikTok session to: ${SESSION_FILE}`);
  console.log('🔒 You can now close Chrome.\n');

  await browser.close();
  process.exit(0);
}

main().catch((err) => {
  console.error('❌ Login error:', err.message);
  process.exit(1);
});
