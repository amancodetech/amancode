'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';
const SCREENSHOT_DIR = path.join(__dirname, '../../../bridge_data/fb_post_screenshots');

async function updateSpecificPageAvatar() {
  if (!fs.existsSync(APP_STATE_PATH)) {
    console.error('❌ Facebook session appstate.json missing');
    process.exit(1);
  }

  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser to update Facebook Page: 61593733289713...');

  const browser = await puppeteer.launch({
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--window-size=1366,900',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 900 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

    const cookies = appState.map(c => ({
      name: c.key || c.name,
      value: c.value,
      domain: (c.domain || 'facebook.com').startsWith('.') ? c.domain : `.${c.domain}`,
      path: c.path || '/',
      httpOnly: c.httpOnly || false,
      secure: c.secure || false,
    }));
    await page.setCookie(...cookies);

    console.log('🔗 Navigating to target Facebook Page:', TARGET_PAGE_URL);
    await page.goto(TARGET_PAGE_URL, { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 5000));

    // Save screenshot of initial state
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'fb_page_before.png') });

    // Look for Profile picture update camera icon / button
    console.log('🔍 Looking for avatar upload button / camera icon on page...');
    
    // Facebook page profile photo has aria-label="تحديث صورة الملف الشخصي" or "Update profile picture" or "تعديل صورة الملف الشخصي" or camera icon
    const avatarBtns = await page.$$('div[aria-label*="صورة"], div[aria-label*="profile"], div[aria-label*="Profile"], div[role="button"][aria-label*="تحديث"], div[role="button"][aria-label*="Update"], div[role="button"][aria-label*="صورة الملف الشخصي"]');
    console.log(`Found ${avatarBtns.length} possible avatar buttons`);

    let clicked = false;
    for (const btn of avatarBtns) {
      const label = await page.evaluate(el => el.getAttribute('aria-label') || '', btn);
      console.log('Checking button aria-label:', label);
      if (label.includes('صورة') || label.includes('profile') || label.includes('Profile') || label.includes('photo')) {
        console.log('👉 Clicking avatar button:', label);
        await btn.click();
        clicked = true;
        await new Promise(r => setTimeout(r, 3000));
        break;
      }
    }

    // Check if file input is available now
    let fileInput = await page.$('input[type="file"]');
    if (!fileInput && !clicked) {
      // Try finding any file input on the page
      fileInput = await page.$('input[type="file"]');
    }

    if (fileInput) {
      console.log('🖼️ Uploading new avatar to Facebook Page:', IMAGE_PATH);
      await fileInput.uploadFile(IMAGE_PATH);
      await new Promise(r => setTimeout(r, 6000));

      // Click "Save" or "حفظ" button in the modal
      const buttons = await page.$$('div[role="button"], button');
      for (const btn of buttons) {
        const text = await page.evaluate(el => el.textContent || el.getAttribute('aria-label') || '', btn);
        if (text && (text.trim() === 'حفظ' || text.trim() === 'Save' || text.includes('حفظ') || text.includes('Save'))) {
          console.log('💾 Clicking Save button:', text.trim());
          await btn.click();
          await new Promise(r => setTimeout(r, 8000));
          break;
        }
      }

      await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'fb_page_after.png') });
      console.log('✅ Target Facebook Page avatar update completed!');
    } else {
      console.log('ℹ️ Searching for Meta Business Suite asset settings for 61593733289713...');
      const mbsUrl = `https://business.facebook.com/latest/settings/profile?asset_id=61593733289713`;
      await page.goto(mbsUrl, { waitUntil: 'networkidle2', timeout: 45000 });
      await new Promise(r => setTimeout(r, 5000));

      const mbsFileInput = await page.$('input[type="file"]');
      if (mbsFileInput) {
        console.log('🖼️ Found file input in Meta Business Suite, uploading...');
        await mbsFileInput.uploadFile(IMAGE_PATH);
        await new Promise(r => setTimeout(r, 8000));
        console.log('✅ Meta Business Suite avatar uploaded for page 61593733289713!');
      } else {
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'fb_page_mbs.png') });
        console.log('📸 Screenshot saved at fb_page_mbs.png');
      }
    }
  } catch (err) {
    console.error('❌ Error during Facebook page update:', err.message);
  } finally {
    await browser.close();
  }
}

updateSpecificPageAvatar();
