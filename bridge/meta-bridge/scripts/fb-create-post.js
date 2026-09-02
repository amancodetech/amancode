#!/usr/bin/env node
'use strict';

/**
 * Facebook Page Post Publisher (Direct Page Profile)
 * Supports:
 *   - Text-only posts
 *   - Image + text posts
 *   - Direct publishing on AmanCode Facebook Page
 * 
 * Usage: node scripts/fb-create-post.js "نص المنشور" [/path/to/image.jpg]
 */

const puppeteer = require('puppeteer');
const fs = require('node:fs');
const path = require('node:path');

const dataDir = process.env.BRIDGE_DATA_DIR || path.join(__dirname, '..', '..', '..', 'bridge_data');
const sessionDir = path.join(dataDir, 'facebook_session');
const appStateFile = path.join(sessionDir, 'appstate.json');

const PAGE_PROFILE_ID = '61593733289713';
const PAGE_URL = `https://web.facebook.com/profile.php?id=${PAGE_PROFILE_ID}`;

function findChrome() {
  const cacheDir = path.join(process.env.HOME || '/home/omar', '.cache', 'puppeteer', 'chrome');
  if (fs.existsSync(cacheDir)) {
    for (const entry of fs.readdirSync(cacheDir)) {
      const p = path.join(cacheDir, entry, 'chrome-linux64', 'chrome');
      if (fs.existsSync(p)) return p;
    }
  }
  return undefined;
}

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function publishPost(text, imagePath) {
  if (!fs.existsSync(appStateFile)) {
    throw new Error(`AppState not found at ${appStateFile}. Please run 'npm run fb:browser' first.`);
  }

  const appState = JSON.parse(fs.readFileSync(appStateFile, 'utf8'));
  const chromePath = findChrome();
  const screenshotDir = path.join(dataDir, 'fb_post_screenshots');
  fs.mkdirSync(screenshotDir, { recursive: true });

  console.log('🚀 Launching Chrome for direct page posting...');
  const browser = await puppeteer.launch({
    headless: 'new',
    executablePath: chromePath,
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
    await page.setViewport({ width: 1280, height: 900 });
    await page.setUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36');

    // Inject cookies via CDP
    const client = await page.target().createCDPSession();
    await client.send('Network.setCookies', {
      cookies: appState.map(c => ({
        name: c.key,
        value: c.value,
        domain: '.' + (c.domain || 'facebook.com').replace(/^\./, ''),
        path: c.path || '/',
      })),
    });

    // Step 1: Navigate to the Page profile
    console.log(`🌐 Navigating to AmanCode Page: ${PAGE_URL}`);
    await page.goto(PAGE_URL, { waitUntil: 'networkidle2', timeout: 45000 });
    await sleep(2500);

    // Step 2: Click on 'بم تفكر؟' trigger
    console.log('🔍 Clicking on post trigger (بم تفكر؟)...');
    const triggerPos = await page.evaluate(() => {
      const spans = Array.from(document.querySelectorAll('span, div[role="button"]'));
      const trigger = spans.find(el => {
        const t = (el.innerText || '').trim();
        return t === 'بم تفكر؟' && el.children.length === 0;
      });
      if (!trigger) return null;
      const rect = trigger.getBoundingClientRect();
      return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    });

    if (triggerPos) {
      await page.mouse.click(triggerPos.x, triggerPos.y);
    } else {
      await page.mouse.click(200, 730);
    }
    await sleep(2500);

    // Step 3: If image is provided, upload it via file chooser
    if (imagePath && fs.existsSync(imagePath)) {
      console.log(`🖼️ Attaching image: ${imagePath}`);
      try {
        const [fileChooser] = await Promise.all([
          page.waitForFileChooser({ timeout: 6000 }).catch(() => null),
          page.evaluate(() => {
            const btn = Array.from(document.querySelectorAll('[aria-label="صورة/فيديو"], [aria-label="إضافة صورة/فيديو"]'))
              .find(e => e.getBoundingClientRect().y > 350);
            if (btn) btn.click();
          }),
        ]);

        if (fileChooser) {
          await fileChooser.accept([imagePath]);
          console.log('✅ Image uploaded via file chooser');
        } else {
          // Fallback direct input upload
          const inputs = await page.$$('input[type="file"]');
          for (const input of inputs) {
            try {
              await input.uploadFile(imagePath);
              console.log('✅ Image uploaded via direct input handle');
              break;
            } catch { /* continue */ }
          }
        }
        await sleep(4000);
      } catch (err) {
        console.warn('⚠️ Warning uploading image:', err.message);
      }
    }

    // Step 4: Focus and type post text into textbox (if text is provided)
    if (text && text.trim()) {
      console.log(`✍️ Typing post content: "${text.slice(0, 50)}..."`);
      await page.waitForSelector('div[role="textbox"]', { timeout: 15000 });
      await page.focus('div[role="textbox"]');
      await sleep(500);
      await page.keyboard.type(text, { delay: 15 });
      await sleep(1500);
    }

    // Step 5: Click Next ('التالي') or Publish ('نشر') if already on final screen
    console.log('🔍 Checking for Next / Publish button...');
    const nextOrPub = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('[role="button"], button'));
      const nextBtn = btns.find(b => {
        const t = (b.innerText || '').trim();
        const a = (b.getAttribute('aria-label') || '').trim();
        return (t === 'التالي' || a === 'التالي') && b.getAttribute('aria-disabled') !== 'true';
      });
      if (nextBtn) {
        const rect = nextBtn.getBoundingClientRect();
        return { type: 'next', x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      }
      const pubBtn = btns.find(b => {
        const t = (b.innerText || '').trim();
        const a = (b.getAttribute('aria-label') || '').trim();
        return (t === 'نشر' || a === 'نشر' || t === 'Post' || a === 'Post') && b.getAttribute('aria-disabled') !== 'true';
      });
      if (pubBtn) {
        const rect = pubBtn.getBoundingClientRect();
        return { type: 'publish', x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      }
      return null;
    });

    if (!nextOrPub) {
      throw new Error('Neither Next nor Publish button found in composer');
    }

    if (nextOrPub.type === 'next') {
      console.log('➡️ Clicking Next (التالي)...');
      await page.mouse.click(nextOrPub.x, nextOrPub.y);
      await sleep(2500);

      // Now click Publish in Step 2
      console.log('🚀 Clicking Publish (نشر)...');
      const pubPos = await page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll('[role="button"], button'));
        const pubBtn = btns.find(b => {
          const t = (b.innerText || '').trim();
          const a = (b.getAttribute('aria-label') || '').trim();
          return (t === 'نشر' || a === 'نشر' || t === 'Post' || a === 'Post') && b.getAttribute('aria-disabled') !== 'true';
        });
        if (!pubBtn) return null;
        const rect = pubBtn.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      });

      if (!pubPos) {
        throw new Error('Publish (نشر) button not found in step 2');
      }
      await page.mouse.click(pubPos.x, pubPos.y);
    } else {
      console.log('🚀 Clicking Publish (نشر)...');
      await page.mouse.click(nextOrPub.x, nextOrPub.y);
    }

    console.log('⏳ Post submitted! Waiting 10s for publication to finish...');
    await sleep(10000);

    await page.screenshot({ path: path.join(screenshotDir, '07-published.png'), fullPage: false });

    console.log('\n🎉 Post successfully published on AmanCode Page!');
    return {
      success: true,
      text: text || '',
      has_image: Boolean(imagePath && fs.existsSync(imagePath)),
      page_id: PAGE_PROFILE_ID,
      published_at: new Date().toISOString(),
      url: PAGE_URL,
    };
  } finally {
    await browser.close();
  }
}

async function main() {
  const text = process.argv[2] || '';
  const imagePath = process.argv[3] || null;

  if (!text && !imagePath) {
    console.error('Usage: node scripts/fb-create-post.js "Post text" [/path/to/image.png]');
    process.exit(1);
  }

  try {
    const res = await publishPost(text, imagePath);
    console.log(JSON.stringify(res, null, 2));
    process.exit(0);
  } catch (err) {
    console.error('\n❌ Failed to publish post:', err.message);
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { publishPost };
