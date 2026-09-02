'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = '/home/omar/Desktop/work/aman-core/bridge_data/facebook_session/appstate.json';
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_user_cover.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';
const SCREENSHOT_PATH = '/home/omar/.gemini/antigravity/brain/adb72d25-6981-4ce1-aef6-b4cfb81675b3/fb_cover_persisted_verified.png';

async function forceSaveCover() {
  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser for complete Facebook cover save & verify...');

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
    console.log('👉 Looking for Cover Photo button...');
    const buttons = await page.$$('div[role="button"]');
    for (const btn of buttons) {
      const label = await page.evaluate(el => (el.getAttribute('aria-label') || el.textContent || '').trim(), btn);
      if (label && (label.includes('صورة غلاف') || label.includes('صورة الغلاف') || label.includes('cover photo') || label.includes('Cover Photo') || label.includes('إضافة صورة غلاف'))) {
        console.log('🎯 Found Cover button:', label);
        await btn.click();
        await new Promise(r => setTimeout(r, 2500));
        break;
      }
    }

    // 2. Click "تحميل صورة" or "اختيار صورة غلاف"
    const menuItems = await page.$$('div[role="menuitem"], div[role="button"], span');
    let uploaderTriggered = false;
    for (const item of menuItems) {
      const txt = await page.evaluate(el => el.textContent || '', item);
      if (txt && (txt.includes('تحميل صورة') || txt.includes('Upload photo') || txt.includes('اختيار صورة') || txt.includes('+ تحميل'))) {
        console.log('👉 Clicking menu item:', txt.trim());
        const [fileChooser] = await Promise.all([
          page.waitForFileChooser({ timeout: 6000 }).catch(() => null),
          item.click(),
        ]);
        if (fileChooser) {
          await fileChooser.accept([IMAGE_PATH]);
          console.log('📂 File accepted by file chooser!');
          uploaderTriggered = true;
        }
        break;
      }
    }

    if (!uploaderTriggered) {
      const finput = await page.$('input[type="file"]');
      if (finput) {
        console.log('🖼️ Attaching file to input directly...');
        await finput.uploadFile(IMAGE_PATH);
      }
    }

    console.log('⏳ Waiting for cover preview to load and Save button to become ready (10s)...');
    await new Promise(r => setTimeout(r, 10000));

    // 3. Find and click "حفظ التغييرات" (Save Changes)
    console.log('👉 Finding and clicking Save Changes button...');
    const saveBtns = await page.$$('div[role="button"], button');
    let clickedSave = false;
    for (const s of saveBtns) {
      const txt = await page.evaluate(el => (el.textContent || el.getAttribute('aria-label') || '').trim(), s);
      if (txt === 'حفظ التغييرات' || txt === 'Save Changes' || txt.includes('حفظ التغييرات')) {
        console.log('💾 Clicking Save Changes button:', txt);
        await s.click();
        clickedSave = true;
        break;
      }
    }

    if (!clickedSave) {
      // Try finding by aria-label
      const ariaSave = await page.$('div[aria-label="حفظ التغييرات"], div[aria-label="Save Changes"]');
      if (ariaSave) {
        console.log('💾 Clicking aria-label Save Changes...');
        await ariaSave.click();
      }
    }

    console.log('⏳ Waiting 15s for Facebook backend to process and persist cover upload...');
    await new Promise(r => setTimeout(r, 15000));

    // 4. HARD RELOAD the page to verify it persisted on Facebook servers!
    console.log('🔄 Reloading page from Facebook server to verify persistence...');
    await page.reload({ waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 5000));

    // 5. Take verified screenshot
    await page.screenshot({ path: SCREENSHOT_PATH });
    console.log('✅ Final verified screenshot saved to:', SCREENSHOT_PATH);
  } catch (err) {
    console.error('❌ Error saving cover:', err.message);
  } finally {
    await browser.close();
  }
}

forceSaveCover();
