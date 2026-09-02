'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = '/home/omar/Desktop/work/aman-core/bridge_data/facebook_session/appstate.json';
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_user_cover.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';
const SCREENSHOT_PATH = '/home/omar/.gemini/antigravity/brain/adb72d25-6981-4ce1-aef6-b4cfb81675b3/fb_cover_exact_verified.png';

async function uploadExactCover() {
  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser to execute exact cover upload ("تحميل صورة")...');

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--window-size=1366,900'],
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

    console.log('🔗 Navigating to Page:', TARGET_PAGE_URL);
    await page.goto(TARGET_PAGE_URL, { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 4000));

    // 1. Click Cover Photo button
    const buttons = await page.$$('div[role="button"]');
    for (const btn of buttons) {
      const label = await page.evaluate(el => (el.getAttribute('aria-label') || el.textContent || '').trim(), btn);
      if (label.includes('صورة غلاف') || label.includes('إضافة صورة غلاف') || label.includes('تعديل صورة الغلاف')) {
        console.log('🎯 Clicking cover button:', label);
        await btn.click();
        await new Promise(r => setTimeout(r, 2000));
        break;
      }
    }

    // 2. Click specifically "تحميل صورة" (role="menuitem")
    console.log('👉 Finding and clicking "تحميل صورة" menuitem...');
    const menuItems = await page.$$('div[role="menuitem"]');
    let fileUploaded = false;
    for (const item of menuItems) {
      const txt = await page.evaluate(el => el.textContent || '', item);
      if (txt.includes('تحميل صورة')) {
        console.log('👉 Found exact "تحميل صورة" menu item! Setting up FileChooser...');
        const [fileChooser] = await Promise.all([
          page.waitForFileChooser({ timeout: 6000 }),
          item.click(),
        ]);
        console.log('📂 Accepting cover image via file chooser:', IMAGE_PATH);
        await fileChooser.accept([IMAGE_PATH]);
        fileUploaded = true;
        break;
      }
    }

    if (!fileUploaded) {
      console.error('❌ Failed to find "تحميل صورة" menu item');
      return;
    }

    console.log('⏳ Waiting for cover image to upload and "حفظ التغييرات" to appear (10s)...');
    await new Promise(r => setTimeout(r, 10000));

    // 3. Click "حفظ التغييرات"
    console.log('👉 Finding and clicking "حفظ التغييرات" button...');
    const saveBtns = await page.$$('div[role="button"], button');
    let saveClicked = false;
    for (const s of saveBtns) {
      const txt = await page.evaluate(el => (el.textContent || el.getAttribute('aria-label') || '').trim(), s);
      if (txt === 'حفظ التغييرات' || txt.includes('حفظ التغييرات')) {
        console.log('💾 Found and clicking Save Changes button:', txt);
        await s.click();
        saveClicked = true;
        break;
      }
    }

    console.log('⏳ Waiting 15s for Facebook servers to persist the cover photo...');
    await new Promise(r => setTimeout(r, 15000));

    // 4. Reload page from server
    console.log('🔄 Reloading page to verify persistence...');
    await page.reload({ waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 5000));

    // 5. Screenshot
    await page.screenshot({ path: SCREENSHOT_PATH });
    console.log('✅ Final verified screenshot saved to:', SCREENSHOT_PATH);
  } catch (err) {
    console.error('❌ Error during exact cover upload:', err.message);
  } finally {
    await browser.close();
  }
}

uploadExactCover();
