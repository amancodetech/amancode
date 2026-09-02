'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const SESSION_PATH = path.join(__dirname, '../../../bridge_data/instagram_session/session.json');
const IMAGE_PATH = process.argv[2] || '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';

async function updateInstagramAvatar() {
  if (!fs.existsSync(SESSION_PATH)) {
    console.error('❌ Instagram session missing');
    process.exit(1);
  }

  const session = JSON.parse(fs.readFileSync(SESSION_PATH, 'utf8'));
  console.log('🌐 Launching browser for Instagram profile update...');

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

    // Set cookies
    const rawCookies = Array.isArray(session.cookies) ? session.cookies : (session.cookies?.cookies || []);
    const cookies = rawCookies.map(c => ({
      name: c.key || c.name,
      value: c.value,
      domain: (c.domain || 'instagram.com').startsWith('.') ? c.domain : `.${c.domain}`,
      path: c.path || '/',
      httpOnly: c.httpOnly || false,
      secure: c.secure || false,
    }));
    await page.setCookie(...cookies);

    console.log('🔗 Navigating to Instagram profile edit page...');
    await page.goto('https://www.instagram.com/accounts/edit/', { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 4000));

    // Look for file input
    const fileInput = await page.$('input[type="file"]');
    if (fileInput) {
      console.log('🖼️ Found profile picture input, uploading new avatar:', IMAGE_PATH);
      await fileInput.uploadFile(IMAGE_PATH);
      await new Promise(r => setTimeout(r, 6000));
      console.log('✅ Instagram avatar uploaded successfully!');
    } else {
      console.log('⚠️ File input not directly visible, trying button trigger...');
      // Click change photo button if available
      const changeButtons = await page.$$('button');
      for (const btn of changeButtons) {
        const text = await page.evaluate(el => el.textContent, btn);
        if (text && (text.includes('Change photo') || text.includes('تغيير الصورة') || text.includes('Change profile photo'))) {
          console.log('👉 Clicking change photo button...');
          await btn.click();
          await new Promise(r => setTimeout(r, 2000));
          const fileInputAfter = await page.$('input[type="file"]');
          if (fileInputAfter) {
            await fileInputAfter.uploadFile(IMAGE_PATH);
            await new Promise(r => setTimeout(r, 6000));
            console.log('✅ Instagram avatar uploaded successfully!');
            break;
          }
        }
      }
    }
  } catch (err) {
    console.error('❌ Error updating Instagram avatar:', err.message);
  } finally {
    await browser.close();
  }
}

updateInstagramAvatar();
