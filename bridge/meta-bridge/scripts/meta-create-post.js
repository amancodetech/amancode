'use strict';
/**
 * Meta Multi-Platform Post Publisher (Facebook + Instagram)
 * Uses Meta Business Suite Composer with stored session cookies.
 *
 * Usage:
 *   node scripts/meta-create-post.js --text "Your post text" --image "/path/to/image.jpg" --platform "all|facebook|instagram"
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const ASSET_ID = process.env.FACEBOOK_PAGE_ID || '1318320251359371';
const BUSINESS_ID = process.env.FACEBOOK_BUSINESS_ID || '1582931449996932';
const APP_STATE_PATH = path.join(__dirname, '../../../bridge_data/facebook_session/appstate.json');

function parseArgs() {
  const args = process.argv.slice(2);
  let text = '';
  let imagePath = '';
  let platform = 'all'; // 'all', 'facebook', 'instagram'

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--text' && args[i + 1]) {
      text = args[++i];
    } else if (args[i] === '--image' && args[i + 1]) {
      imagePath = args[++i];
    } else if (args[i] === '--platform' && args[i + 1]) {
      platform = args[++i].toLowerCase();
    } else if (!text && !args[i].startsWith('--')) {
      text = args[i];
    } else if (!imagePath && !args[i].startsWith('--')) {
      imagePath = args[i];
    }
  }
  return { text, imagePath, platform };
}

async function publishPost() {
  const { text, imagePath, platform } = parseArgs();

  if (!fs.existsSync(APP_STATE_PATH)) {
    console.error('❌ Error: appstate.json missing at', APP_STATE_PATH);
    process.exit(1);
  }

  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));

  console.log('🌐 Launching browser to publish on Meta (FB / Instagram)...');
  console.log('📝 Platform:', platform);
  console.log('📝 Text:', text ? text.slice(0, 80) + '...' : '(No text)');
  console.log('🖼️ Image:', imagePath || '(No image)');

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

    const composerUrl = `https://business.facebook.com/latest/composer/?asset_id=${ASSET_ID}&business_id=${BUSINESS_ID}`;
    console.log('🌐 Opening Meta Business Suite Composer...');
    await page.goto(composerUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await new Promise(r => setTimeout(r, 6000));

    // If image provided, attach it
    if (imagePath && fs.existsSync(imagePath)) {
      console.log('🖼️ Attaching image file:', imagePath);
      const [fileChooser] = await Promise.all([
        page.waitForFileChooser({ timeout: 15000 }).catch(() => null),
        page.evaluate(() => {
          const btns = Array.from(document.querySelectorAll('[role=button], div[tabindex]'));
          const addBtn = btns.find(b => (b.innerText || '').includes('إضافة صورة') || (b.innerText || '').includes('إضافة صورة/فيديو') || (b.innerText || '').includes('وسائط'));
          if (addBtn) addBtn.click();
        }),
      ]);

      if (fileChooser) {
        await fileChooser.accept([path.resolve(imagePath)]);
        console.log('✅ Image uploaded via file chooser!');
        await new Promise(r => setTimeout(r, 5000));
      } else {
        const fileInput = await page.$('input[type=file]');
        if (fileInput) {
          await fileInput.uploadFile(path.resolve(imagePath));
          console.log('✅ Image uploaded via file input!');
          await new Promise(r => setTimeout(r, 5000));
        } else {
          console.warn('⚠️ Could not find file chooser, proceeding without image');
        }
      }
    }

    // Enter post text
    if (text) {
      console.log('✍️ Entering post text...');
      const textbox = await page.$('div[role="combobox"][contenteditable="true"], div[role="textbox"][contenteditable="true"], div[contenteditable="true"]');
      if (textbox) {
        await textbox.click();
        await new Promise(r => setTimeout(r, 400));
        await page.keyboard.type(text, { delay: 15 });
        console.log('✅ Post text typed successfully!');
      } else {
        console.warn('⚠️ Textbox not found, trying focus...');
      }
    }

    await new Promise(r => setTimeout(r, 2000));

    // Click Publish ("نشر")
    console.log('🚀 Publishing post...');
    const published = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('[role=button], button'));
      const pubBtn = btns.find(b => (b.innerText || '').trim() === 'نشر' || (b.innerText || '').trim() === 'Publish');
      if (pubBtn) {
        pubBtn.click();
        return true;
      }
      return false;
    });

    if (published) {
      console.log('⏳ Waiting for publishing confirmation...');
      await new Promise(r => setTimeout(r, 8000));
      console.log('🎉 Post successfully published to Meta (Facebook / Instagram)!');
    } else {
      console.error('❌ Could not find Publish button.');
      process.exit(1);
    }

    await browser.close();
    console.log('✅ Completed successfully.');
    process.exit(0);
  } catch (err) {
    console.error('❌ Error publishing post:', err.message);
    try { await browser.close(); } catch {}
    process.exit(1);
  }
}

publishPost();
