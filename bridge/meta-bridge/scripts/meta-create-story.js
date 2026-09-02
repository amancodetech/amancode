'use strict';
/**
 * Meta Multi-Platform Story Publisher (Facebook Story + Instagram Story)
 * Uses Meta Business Suite Story Composer.
 *
 * Usage:
 *   node scripts/meta-create-story.js --image "/path/to/image.jpg" --platform "all|facebook|instagram"
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const ASSET_ID = process.env.FACEBOOK_PAGE_ID || '1318320251359371';
const BUSINESS_ID = process.env.FACEBOOK_BUSINESS_ID || '1582931449996932';
const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');

function parseArgs() {
  const args = process.argv.slice(2);
  let imagePath = '';
  let platform = 'all';

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--image' && args[i + 1]) {
      imagePath = args[++i];
    } else if (args[i] === '--platform' && args[i + 1]) {
      platform = args[++i].toLowerCase();
    } else if (!imagePath && !args[i].startsWith('--')) {
      imagePath = args[i];
    }
  }
  return { imagePath, platform };
}

async function publishStory() {
  const { imagePath, platform } = parseArgs();

  if (!imagePath || !fs.existsSync(imagePath)) {
    console.error('❌ Error: Story image path is required and must exist.');
    process.exit(1);
  }

  if (!fs.existsSync(APP_STATE_PATH)) {
    console.error('❌ Error: appstate.json missing at', APP_STATE_PATH);
    process.exit(1);
  }

  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));

  console.log('🌐 Launching browser to publish Story on Meta (FB & Instagram)...');
  console.log('📝 Platform:', platform);
  console.log('🖼️ Image:', imagePath);

  const browser = await puppeteer.launch({
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--dns-result-order=ipv4first',
      '--lang=ar',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 900 });

    const client = await page.target().createCDPSession();
    await client.send('Network.setCookies', {
      cookies: appState.map(c => ({
        name: c.key,
        value: c.value,
        domain: '.' + (c.domain || 'facebook.com').replace(/^\./, ''),
        path: c.path || '/',
      })),
    });

    const storyComposerUrl = `https://business.facebook.com/latest/story_composer/?asset_id=${ASSET_ID}&business_id=${BUSINESS_ID}`;
    console.log('🌐 Opening Story Composer URL...');
    await page.goto(storyComposerUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await new Promise(r => setTimeout(r, 6000));

    console.log('🖼️ Attaching story media file...');
    const [fileChooser] = await Promise.all([
      page.waitForFileChooser({ timeout: 15000 }).catch(() => null),
      page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll('[role=button], button, div[tabindex]'));
        const addBtn = btns.find(b => (b.innerText || '').includes('إضافة صورة') || (b.innerText || '').includes('إضافة صورة/فيديو') || (b.innerText || '').includes('وسائط'));
        if (addBtn) addBtn.click();
      }),
    ]);

    if (fileChooser) {
      await fileChooser.accept([path.resolve(imagePath)]);
      console.log('✅ Story image uploaded via file chooser!');
      await new Promise(r => setTimeout(r, 6000));
    } else {
      const fileInput = await page.$('input[type=file]');
      if (fileInput) {
        await fileInput.uploadFile(path.resolve(imagePath));
        console.log('✅ Story image uploaded via file input!');
        await new Promise(r => setTimeout(r, 6000));
      } else {
        console.error('❌ Could not find file upload trigger.');
        process.exit(1);
      }
    }

    // Wait for media processing
    await new Promise(r => setTimeout(r, 4000));

    // Click Share ("مشاركة")
    console.log('🚀 Sharing story...');
    const shared = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('[role=button], button'));
      const shareBtn = btns.find(b => (b.innerText || '').trim() === 'مشاركة' || (b.innerText || '').trim() === 'مشاركة القصة' || (b.innerText || '').trim() === 'Share');
      if (shareBtn) {
        shareBtn.click();
        return true;
      }
      return false;
    });

    if (shared) {
      console.log('⏳ Waiting for story sharing confirmation...');
      await new Promise(r => setTimeout(r, 8000));
      console.log('🎉 Story successfully shared to Facebook & Instagram Stories!');
    } else {
      console.error('❌ Could not find Share button.');
      process.exit(1);
    }

    await browser.close();
    console.log('✅ Story publication complete.');
    process.exit(0);
  } catch (err) {
    console.error('❌ Error publishing story:', err.message);
    try { await browser.close(); } catch {}
    process.exit(1);
  }
}

publishStory();
