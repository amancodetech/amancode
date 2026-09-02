'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';
const SCREENSHOT_DIR = path.join(__dirname, '../../../bridge_data/fb_post_screenshots');

async function updateProfilePictureExact() {
  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  console.log('🌐 Launching browser to update Profile Picture (not cover) on Facebook...');

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
    await new Promise(r => setTimeout(r, 5000));

    // Find the circular profile photo camera button specifically
    // It is an aria-label containing "الملف الشخصي" or "profile" but NOT "غلاف" or "cover"
    const buttons = await page.$$('div[role="button"]');
    console.log(`Scanning ${buttons.length} role="button" elements...`);

    let targetBtn = null;
    for (const btn of buttons) {
      const label = await page.evaluate(el => el.getAttribute('aria-label') || '', btn);
      if (label) {
        const isCover = label.includes('غلاف') || label.includes('cover') || label.includes('Cover');
        const isProfile = label.includes('الملف الشخصي') || label.includes('profile') || label.includes('Profile') || label.includes('صورة');
        if (isProfile && !isCover) {
          console.log('🎯 Found exact Profile Picture button:', label);
          targetBtn = btn;
          break;
        }
      }
    }

    if (targetBtn) {
      console.log('👉 Clicking Profile Picture button...');
      await targetBtn.click();
      await new Promise(r => setTimeout(r, 3000));

      // After clicking, check if "تحميل صورة" or "Upload photo" item appears in menu
      const menuItems = await page.$$('div[role="menuitem"], span, div[role="button"]');
      for (const item of menuItems) {
        const txt = await page.evaluate(el => el.textContent || '', item);
        if (txt && (txt.includes('تحميل صورة') || txt.includes('Upload photo') || txt.includes('اختيار صورة'))) {
          console.log('👉 Clicking menu item:', txt.trim());
          await item.click();
          await new Promise(r => setTimeout(r, 2000));
          break;
        }
      }

      // Check file input
      const fileInput = await page.$('input[type="file"]');
      if (fileInput) {
        console.log('🖼️ Found file input, uploading:', IMAGE_PATH);
        await fileInput.uploadFile(IMAGE_PATH);
        await new Promise(r => setTimeout(r, 6000));

        // Click Save button in crop/modal dialog
        const dialogBtns = await page.$$('div[role="dialog"] div[role="button"], div[role="dialog"] button, div[aria-label="حفظ"], div[aria-label="Save"]');
        for (const dBtn of dialogBtns) {
          const dTxt = await page.evaluate(el => el.textContent || el.getAttribute('aria-label') || '', dBtn);
          if (dTxt && (dTxt.trim() === 'حفظ' || dTxt.trim() === 'Save' || dTxt.includes('حفظ') || dTxt.includes('Save'))) {
            console.log('💾 Clicking dialog Save button:', dTxt.trim());
            await dBtn.click();
            await new Promise(r => setTimeout(r, 8000));
            break;
          }
        }
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'fb_profile_updated.png') });
        console.log('✅ Profile Picture updated successfully on Facebook Page!');
      }
    } else {
      console.log('⚠️ Specific profile button not found by label, trying direct camera icon click on profile avatar');
    }
  } catch (err) {
    console.error('❌ Error updating profile picture:', err.message);
  } finally {
    await browser.close();
  }
}

updateProfilePictureExact();
