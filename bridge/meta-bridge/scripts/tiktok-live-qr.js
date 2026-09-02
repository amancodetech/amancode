'use strict';
/**
 * TikTok Live QR Code Login Daemon
 * Captures live QR code, refreshes screenshot, and waits for user mobile scan.
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '../../../bridge_data/tiktok_session');
const SESSION_FILE = path.join(DATA_DIR, 'session.json');
const QR_IMG_PATH = '/home/omar/.gemini/antigravity/brain/adb72d25-6981-4ce1-aef6-b4cfb81675b3/tiktok_qr.png';
const BRAVE_PATH = '/snap/bin/brave';

async function main() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.mkdirSync(path.dirname(QR_IMG_PATH), { recursive: true });

  console.log('🌐 Launching headless browser for TikTok QR Code login...');

  const browser = await puppeteer.launch({
    executablePath: fs.existsSync(BRAVE_PATH) ? BRAVE_PATH : undefined,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
      '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      '--lang=ar,en',
    ],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1366, height: 900 });

  await page.evaluateOnNewDocument(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  });

  console.log('🌐 Navigating to TikTok QR login page...');
  await page.goto('https://www.tiktok.com/login/qrcode', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await new Promise(r => setTimeout(r, 6000));

  async function captureQr() {
    try {
      const qrBox = await page.$('canvas, div[class*="qrcode" i], div[class*="Qrcode" i], div[data-e2e="qr-code"]');
      if (qrBox) {
        await qrBox.screenshot({ path: QR_IMG_PATH });
      } else {
        await page.screenshot({ path: QR_IMG_PATH });
      }
      console.log(`📸 Updated QR Code screenshot at ${new Date().toLocaleTimeString()}`);
    } catch (e) {
      console.warn('⚠️ Could not capture QR:', e.message);
    }
  }

  await captureQr();
  console.log('✅ QR Code is ready for scanning!');

  const maxWaitMs = 180000; // 3 minutes
  const startTime = Date.now();
  let loggedIn = false;

  while (Date.now() - startTime < maxWaitMs) {
    await new Promise(r => setTimeout(r, 4000));

    const client = await page.target().createCDPSession();
    const { cookies } = await client.send('Network.getAllCookies');

    const hasSession = cookies.some(c => c.name === 'sessionid' || c.name === 'sessionid_ss' || (c.name === 'sid_tt' && c.value));
    const currentUrl = page.url();

    if (hasSession || (!currentUrl.includes('/login') && !currentUrl.includes('/qrcode'))) {
      console.log('🎉 Login detected! Capturing session...');
      const sessionData = {
        capturedAt: new Date().toISOString(),
        url: currentUrl,
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
      console.log(`💾 Saved ${cookies.length} cookies to ${SESSION_FILE}`);
      console.log('✅ TikTok Authentication Complete!');
      loggedIn = true;
      break;
    }

    // Refresh QR code screenshot every 16 seconds or if refreshed
    if ((Math.floor((Date.now() - startTime) / 1000) % 16) === 0) {
      await captureQr();
    }
  }

  await browser.close();

  if (!loggedIn) {
    console.error('⌛ QR code login timed out (3 minutes). Please run again.');
    process.exit(1);
  }

  process.exit(0);
}

main().catch((err) => {
  console.error('❌ Error in TikTok live QR:', err.message);
  process.exit(1);
});
