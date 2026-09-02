'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_avatar_white_1024.jpg';
const TARGET_URL = 'https://studio.youtube.com/channel/UCUe2qwyWetGJUxfP9JxWtAg/editing/branding';
const USER_DATA_DIR = path.join(process.env.HOME, '.config/google-chrome');

async function updateYouTubeAvatar() {
  console.log('🌐 Launching Chrome to update YouTube Studio avatar...');

  // Try connecting to existing browser or launch with profile
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: 'new',
      userDataDir: path.join(__dirname, '../../../bridge_data/google_browser_profile'),
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-gpu',
        '--window-size=1366,900'
      ]
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 900 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

    console.log('🔗 Navigating to YouTube Studio branding page:', TARGET_URL);
    await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 45000 });
    await new Promise(r => setTimeout(r, 5000));

    const currentUrl = page.url();
    console.log('Page loaded URL:', currentUrl);

    if (currentUrl.includes('accounts.google.com/signin') || currentUrl.includes('ServiceLogin')) {
      console.log('ℹ️ Google session requires login in this profile.');
    } else {
      // Find Picture upload button
      console.log('🔍 Looking for Avatar Upload / Change button on YouTube Studio...');
      const uploadButtons = await page.$$('button, ytcp-button, ytcp-button-shape');
      for (const btn of uploadButtons) {
        const txt = await page.evaluate(el => el.textContent || '', btn);
        if (txt && (txt.includes('Upload') || txt.includes('تحميل') || txt.includes('Change') || txt.includes('تغيير'))) {
          console.log('👉 Found upload button:', txt.trim());
          const [fileChooser] = await Promise.all([
            page.waitForFileChooser({ timeout: 5000 }).catch(() => null),
            btn.click(),
          ]);
          if (fileChooser) {
            await fileChooser.accept([IMAGE_PATH]);
            console.log('📂 File selected:', IMAGE_PATH);
            await new Promise(r => setTimeout(r, 4000));

            // Click Done in crop dialog
            const doneBtns = await page.$$('button, ytcp-button');
            for (const dBtn of doneBtns) {
              const dTxt = await page.evaluate(el => el.textContent || '', dBtn);
              if (dTxt && (dTxt.includes('Done') || dTxt.includes('تم'))) {
                console.log('👉 Clicking Done button:', dTxt.trim());
                await dBtn.click();
                await new Promise(r => setTimeout(r, 3000));
                break;
              }
            }

            // Click Publish
            const pubBtns = await page.$$('button, ytcp-button');
            for (const pBtn of pubBtns) {
              const pTxt = await page.evaluate(el => el.textContent || '', pBtn);
              if (pTxt && (pTxt.includes('Publish') || pTxt.includes('نشر'))) {
                console.log('💾 Clicking Publish button:', pTxt.trim());
                await pBtn.click();
                await new Promise(r => setTimeout(r, 6000));
                console.log('✅ YouTube Channel Avatar published successfully!');
                break;
              }
            }
          }
          break;
        }
      }
    }
  } catch (err) {
    console.error('❌ Error during YouTube avatar update:', err.message);
  } finally {
    if (browser) await browser.close();
  }
}

updateYouTubeAvatar();
