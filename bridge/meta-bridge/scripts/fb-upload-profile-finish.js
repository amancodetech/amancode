'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';
const SCREENSHOT_DIR = path.join(__dirname, '../../../bridge_data/fb_post_screenshots');

async function uploadProfilePictureFinish() {
  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser for complete Facebook profile picture upload & save...');

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

    // Step 1: Click Profile Picture camera / actions button
    const buttons = await page.$$('div[role="button"]');
    for (const btn of buttons) {
      const label = await page.evaluate(el => el.getAttribute('aria-label') || '', btn);
      if (label && (label.includes('إجراءات صورة الملف الشخصي') || (label.includes('صورة') && label.includes('الملف الشخصي') && !label.includes('غلاف')))) {
        console.log('👉 Clicking Profile Actions button:', label);
        await btn.click();
        await new Promise(r => setTimeout(r, 3000));
        break;
      }
    }

    // Step 2: In modal, look for "+ تحميل صورة" button or file input
    console.log('🔍 Looking for "+ تحميل صورة" button...');
    const uploadBtns = await page.$$('div[role="dialog"] div[role="button"], div[role="dialog"] span, div[role="dialog"] button');
    let uploadBtnClicked = false;
    for (const uBtn of uploadBtns) {
      const txt = await page.evaluate(el => el.textContent || '', uBtn);
      if (txt && (txt.includes('تحميل صورة') || txt.includes('Upload Photo') || txt.includes('+ تحميل'))) {
        console.log('👉 Found and clicking "+ تحميل صورة":', txt.trim());
        
        // Setup file chooser listener if clicking opens file chooser
        const [fileChooser] = await Promise.all([
          page.waitForFileChooser({ timeout: 5000 }).catch(() => null),
          uBtn.click(),
        ]);

        if (fileChooser) {
          console.log('📂 FileChooser intercepted, accepting file:', IMAGE_PATH);
          await fileChooser.accept([IMAGE_PATH]);
          uploadBtnClicked = true;
        }
        break;
      }
    }

    // Fallback: direct file input upload inside dialog
    if (!uploadBtnClicked) {
      const fileInput = await page.$('div[role="dialog"] input[type="file"], input[type="file"]');
      if (fileInput) {
        console.log('🖼️ Attaching directly to file input:', IMAGE_PATH);
        await fileInput.uploadFile(IMAGE_PATH);
      }
    }

    console.log('⏳ Waiting for photo upload and crop dialog to load (8s)...');
    await new Promise(r => setTimeout(r, 8000));

    // Step 3: Click the final "حفظ" (Save) button in the Crop dialog
    console.log('🔍 Finding final "حفظ" (Save) button in crop dialog...');
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_crop_dialog_before_save.png') });

    const allButtons = await page.$$('div[role="dialog"] div[role="button"], div[role="dialog"] button');
    let saveClicked = false;
    for (const sBtn of allButtons) {
      const sTxt = await page.evaluate(el => (el.textContent || el.getAttribute('aria-label') || '').trim(), sBtn);
      if (sTxt === 'حفظ' || sTxt === 'Save' || sTxt.includes('حفظ') || sTxt.includes('Save')) {
        console.log('💾 Found and clicking Save button:', sTxt);
        await sBtn.click();
        saveClicked = true;
        await new Promise(r => setTimeout(r, 10000));
        break;
      }
    }

    // Step 4: Final verification screenshot
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_page_final_after_save.png') });
    console.log('📸 Final screenshot saved to 02_page_final_after_save.png (saveClicked=' + saveClicked + ')');
  } catch (err) {
    console.error('❌ Error during avatar upload:', err.message);
  } finally {
    await browser.close();
  }
}

uploadProfilePictureFinish();
