'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const USER_DATA_DIR = path.join(__dirname, '../../../bridge_data/tiktok_session/chrome_profile');
const IMAGE_PATH = process.argv[2] || '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';

async function updateTikTokAvatar() {
  console.log('🌐 Launching browser for TikTok profile update...');

  const browser = await puppeteer.launch({
    executablePath: fs.existsSync('/snap/bin/brave') ? '/snap/bin/brave' : undefined,
    headless: 'new',
    userDataDir: USER_DATA_DIR,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--window-size=1280,800',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

    console.log('🔗 Navigating to TikTok profile settings...');
    await page.goto('https://www.tiktok.com/profile', { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 4000));

    // Try clicking edit profile
    const editBtns = await page.$$('button, a');
    for (const btn of editBtns) {
      const txt = await page.evaluate(el => el.textContent, btn);
      if (txt && (txt.includes('Edit profile') || txt.includes('تعديل الملف الشخصي'))) {
        console.log('👉 Clicking Edit Profile button...');
        await btn.click();
        await new Promise(r => setTimeout(r, 3000));
        break;
      }
    }

    const fileInput = await page.$('input[type="file"]');
    if (fileInput) {
      console.log('🖼️ Found file input, uploading new avatar:', IMAGE_PATH);
      await fileInput.uploadFile(IMAGE_PATH);
      await new Promise(r => setTimeout(r, 6000));

      // Click save button if modal opened
      const saveBtns = await page.$$('button');
      for (const btn of saveBtns) {
        const txt = await page.evaluate(el => el.textContent, btn);
        if (txt && (txt.includes('Save') || txt.includes('Apply') || txt.includes('حفظ') || txt.includes('تطبيق'))) {
          console.log('💾 Clicking Save/Apply button...');
          await btn.click();
          await new Promise(r => setTimeout(r, 4000));
          break;
        }
      }
      console.log('✅ TikTok avatar uploaded successfully!');
    } else {
      console.log('ℹ️ TikTok profile page loaded.');
    }
  } catch (err) {
    console.error('❌ TikTok update info:', err.message);
  } finally {
    await browser.close();
  }
}

updateTikTokAvatar();
