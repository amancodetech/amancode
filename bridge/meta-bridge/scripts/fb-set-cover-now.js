'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_facebook_cover.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';
const SCREENSHOT_DIR = path.join(__dirname, '../../../bridge_data/fb_post_screenshots');

async function setCoverPicNow() {
  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser for Facebook page COVER banner update...');

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

    // 1. Find and click the Cover Photo button ("إضافة صورة غلاف" or "تعديل صورة الغلاف")
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

    // 2. Click "تحميل صورة" or "Upload photo" in cover menu
    console.log('👉 Looking for "تحميل صورة" in cover menu...');
    const menuItems = await page.$$('div[role="menuitem"], div[role="button"], span');
    let uploaderTriggered = false;
    for (const item of menuItems) {
      const txt = await page.evaluate(el => el.textContent || '', item);
      if (txt && (txt.includes('تحميل صورة') || txt.includes('Upload photo') || txt.includes('اختيار صورة'))) {
        console.log('👉 Clicking cover menu item:', txt.trim());
        const [fileChooser] = await Promise.all([
          page.waitForFileChooser({ timeout: 6000 }).catch(() => null),
          item.click(),
        ]);
        if (fileChooser) {
          await fileChooser.accept([IMAGE_PATH]);
          console.log('📂 FileChooser accepted cover image:', IMAGE_PATH);
          uploaderTriggered = true;
        }
        break;
      }
    }

    // Fallback: direct file input upload
    if (!uploaderTriggered) {
      const finput = await page.$('input[type="file"]');
      if (finput) {
        console.log('🖼️ Attaching directly to file input...');
        await finput.uploadFile(IMAGE_PATH);
        uploaderTriggered = true;
      }
    }

    console.log('⏳ Waiting for cover image to render and Save button to appear (8s)...');
    await new Promise(r => setTimeout(r, 8000));

    // 3. Click the blue "حفظ التغييرات" (Save Changes) button
    console.log('👉 Looking for "حفظ التغييرات" button...');
    const saveBtns = await page.$$('div[role="button"], button');
    for (const s of saveBtns) {
      const txt = await page.evaluate(el => (el.textContent || el.getAttribute('aria-label') || '').trim(), s);
      if (txt === 'حفظ التغييرات' || txt === 'Save Changes' || txt.includes('حفظ التغييرات')) {
        console.log('💾 Found and clicking Save Changes button:', txt);
        await s.click();
        await new Promise(r => setTimeout(r, 10000));
        break;
      }
    }

    // 4. Save final screenshot
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_cover_final_success.png') });
    console.log('✅ Cover update process completed! Screenshot saved to 04_cover_final_success.png');
  } catch (err) {
    console.error('❌ Error during cover update:', err.message);
  } finally {
    await browser.close();
  }
}

setCoverPicNow();
