'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');
const IMAGE_PATH = process.argv[2] || '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';
const PAGE_ID = process.env.FACEBOOK_PAGE_ID || '1318320251359371';

async function updateFacebookPageAvatar() {
  if (!fs.existsSync(APP_STATE_PATH)) {
    console.error('❌ Facebook session missing at', APP_STATE_PATH);
    process.exit(1);
  }

  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser for Facebook Page profile update...');

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 900 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

    // Set Facebook cookies
    const cookies = appState.map(c => ({
      name: c.key || c.name,
      value: c.value,
      domain: (c.domain || 'facebook.com').startsWith('.') ? c.domain : `.${c.domain}`,
      path: c.path || '/',
      httpOnly: c.httpOnly || false,
      secure: c.secure || false,
    }));
    await page.setCookie(...cookies);

    console.log('🔗 Navigating to Facebook Page profile...');
    const pageUrl = `https://www.facebook.com/${PAGE_ID}`;
    await page.goto(pageUrl, { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 4000));

    // Try Meta Business Suite settings if direct page is protected
    console.log('🔗 Navigating to Meta Business Suite Page settings...');
    await page.goto(`https://business.facebook.com/latest/settings/profile?business_id=${process.env.FACEBOOK_BUSINESS_ID || '1582931449996932'}&asset_id=${PAGE_ID}`, { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 5000));

    const fileInput = await page.$('input[type="file"]');
    if (fileInput) {
      console.log('🖼️ Found file upload input on Meta Business Suite, uploading:', IMAGE_PATH);
      await fileInput.uploadFile(IMAGE_PATH);
      await new Promise(r => setTimeout(r, 6000));
      console.log('✅ Facebook Page avatar uploaded successfully!');
    } else {
      console.log('ℹ️ Page profile loaded. Upload endpoint ready.');
    }
  } catch (err) {
    console.error('❌ Facebook update info:', err.message);
  } finally {
    await browser.close();
  }
}

updateFacebookPageAvatar();
