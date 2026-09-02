'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';
const SCREENSHOT_DIR = path.join(__dirname, '../../../bridge_data/fb_post_screenshots');

async function setProfilePicNow() {
  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser for Facebook page avatar update...');

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

    // 0. Dismiss any pending cover photo changes
    const cancelBtns = await page.$$('div[role="button"], button');
    for (const b of cancelBtns) {
      const txt = await page.evaluate(el => el.textContent || '', b);
      if (txt && (txt.trim() === 'إلغاء' || txt.trim() === 'Cancel')) {
        console.log('👉 Dismissing pending cover changes...');
        await b.click();
        await new Promise(r => setTimeout(r, 2000));
        break;
      }
    }

    // 1. Click Profile camera icon
    console.log('👉 Clicking Profile camera button...');
    const avatarBtns = await page.$$('div[role="button"]');
    for (const btn of avatarBtns) {
      const label = await page.evaluate(el => el.getAttribute('aria-label') || '', btn);
      if (label && (label.includes('إجراءات صورة الملف الشخصي') || (label.includes('صورة') && label.includes('الملف الشخصي') && !label.includes('غلاف')))) {
        await btn.click();
        await new Promise(r => setTimeout(r, 2500));
        break;
      }
    }

    // 2. Click "اختيار صورة ملف شخصي" in popup menu
    console.log('👉 Looking for "اختيار صورة ملف شخصي" menu item...');
    const menuItems = await page.$$('div[role="menuitem"], div[role="button"], span');
    let menuClicked = false;
    for (const item of menuItems) {
      const txt = await page.evaluate(el => el.textContent || '', item);
      if (txt && txt.includes('اختيار صورة ملف شخصي')) {
        console.log('👉 Found and clicking:', txt.trim());
        await item.click();
        menuClicked = true;
        await new Promise(r => setTimeout(r, 3000));
        break;
      }
    }

    // 3. In the modal "اختيار صورة ملف شخصي", click "+ تحميل صورة" with file chooser
    console.log('👉 Looking for "+ تحميل صورة" button in modal dialog...');
    const dialogElements = await page.$$('div[role="dialog"] div[role="button"], div[role="dialog"] span, div[role="dialog"] button');
    for (const el of dialogElements) {
      const txt = await page.evaluate(e => e.textContent || '', el);
      if (txt && (txt.includes('تحميل صورة') || txt.includes('Upload Photo') || txt.includes('+ تحميل'))) {
        console.log('👉 Clicking "+ تحميل صورة" and attaching file:', IMAGE_PATH);
        const [fileChooser] = await Promise.all([
          page.waitForFileChooser({ timeout: 6000 }).catch(() => null),
          el.click(),
        ]);
        if (fileChooser) {
          await fileChooser.accept([IMAGE_PATH]);
          console.log('📂 File selected successfully!');
        } else {
          // Direct file input fallback
          const finput = await page.$('input[type="file"]');
          if (finput) await finput.uploadFile(IMAGE_PATH);
        }
        break;
      }
    }

    console.log('⏳ Waiting for photo crop dialog (6s)...');
    await new Promise(r => setTimeout(r, 6000));

    // 4. Click the blue "حفظ" button
    console.log('👉 Looking for Save ("حفظ") button...');
    const saveBtns = await page.$$('div[role="dialog"] div[role="button"], div[role="dialog"] button, div[aria-label="حفظ"]');
    for (const s of saveBtns) {
      const txt = await page.evaluate(el => (el.textContent || el.getAttribute('aria-label') || '').trim(), s);
      if (txt === 'حفظ' || txt === 'Save' || (txt.includes('حفظ') && !txt.includes('التغييرات'))) {
        console.log('💾 Clicking Save button:', txt);
        await s.click();
        await new Promise(r => setTimeout(r, 10000));
        break;
      }
    }

    // 5. Save final result screenshot
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_final_avatar_success.png') });
    console.log('✅ Final screenshot saved to 03_final_avatar_success.png!');
  } catch (err) {
    console.error('❌ Error:', err.message);
  } finally {
    await browser.close();
  }
}

setProfilePicNow();
