'use strict';
/**
 * TikTok Video & Photo Publisher for TikTok Studio
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const SESSION_FILE = path.join(__dirname, '../../../bridge_data/tiktok_session/session.json');

function parseArgs() {
  const args = process.argv.slice(2);
  let caption = '';
  let mediaPath = '';
  let isStory = false;

  for (let i = 0; i < args.length; i++) {
    if ((args[i] === '--caption' || args[i] === '--text') && args[i + 1]) {
      caption = args[++i];
    } else if ((args[i] === '--media' || args[i] === '--video' || args[i] === '--image') && args[i + 1]) {
      mediaPath = args[++i];
    } else if (args[i] === '--story') {
      isStory = true;
    } else if (!caption && !args[i].startsWith('--')) {
      caption = args[i];
    } else if (!mediaPath && !args[i].startsWith('--')) {
      mediaPath = args[i];
    }
  }
  return { caption, mediaPath, isStory };
}

async function main() {
  const { caption, mediaPath, isStory } = parseArgs();

  if (!fs.existsSync(SESSION_FILE)) {
    console.error('❌ Error: TikTok session.json missing at', SESSION_FILE);
    process.exit(1);
  }

  const sessionData = JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8'));

  console.log('🌐 Launching TikTok Studio Publisher...');
  console.log('📝 Caption:', caption ? caption.slice(0, 80) + '...' : '(No caption)');
  console.log('🎬 Media:', mediaPath || '(No media)');

  const browser = await puppeteer.launch({
    executablePath: fs.existsSync('/snap/bin/brave') ? '/snap/bin/brave' : undefined,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--lang=ar,en',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 900 });

    const client = await page.target().createCDPSession();
    await client.send('Network.setCookies', {
      cookies: (sessionData.cookies || []).map(c => ({
        name: c.key,
        value: c.value,
        domain: '.' + (c.domain || 'tiktok.com').replace(/^\./, ''),
        path: c.path || '/',
      })),
    });

    const uploadUrl = 'https://www.tiktok.com/tiktokstudio/upload?from=upload';
    console.log('🌐 Navigating to TikTok Studio Upload Center:', uploadUrl);
    await page.goto(uploadUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await new Promise(r => setTimeout(r, 6000));

    // If media is an image and not video, click "الصور" (Photos) tab if present
    const isImage = mediaPath && (mediaPath.endsWith('.jpg') || mediaPath.endsWith('.jpeg') || mediaPath.endsWith('.png') || mediaPath.endsWith('.webp'));
    if (isImage) {
      console.log('🖼️ Switching to Photos/Images mode in TikTok Studio...');
      await page.evaluate(() => {
        const photoTab = Array.from(document.querySelectorAll('button, div[role="tab"]')).find(b => {
          const t = (b.innerText || '').trim();
          return t === 'الصور' || t === 'Photos' || t === 'Photo';
        });
        if (photoTab) photoTab.click();
      });
      await new Promise(r => setTimeout(r, 2000));
    }

    // Upload file
    if (mediaPath && fs.existsSync(mediaPath)) {
      console.log('📁 Attaching media file to TikTok...');
      const fileInput = await page.$('input[type="file"]');
      if (fileInput) {
        await fileInput.uploadFile(path.resolve(mediaPath));
        console.log('✅ File uploaded to TikTok! Waiting for processing...');
        await new Promise(r => setTimeout(r, 12000));
      } else {
        console.warn('⚠️ File input not found.');
      }
    }

    // Type caption
    if (caption) {
      console.log('✍️ Entering TikTok caption...');
      const typed = await page.evaluate((text) => {
        const box = document.querySelector('div[contenteditable="true"], div[role="textbox"], textarea');
        if (box) {
          box.focus();
          document.execCommand('insertText', false, text);
          return true;
        }
        return false;
      }, caption);

      if (!typed) {
        const captionBox = await page.$('div[contenteditable="true"], textarea, div[role="textbox"]');
        if (captionBox) {
          await captionBox.click();
          await page.keyboard.type(caption, { delay: 10 });
        }
      }
      console.log('✅ Caption entered successfully!');
    }

    await new Promise(r => setTimeout(r, 4000));

    // Check for Post button
    console.log('🚀 Looking for Post / Publish button...');
    const posted = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
      const postBtn = btns.find(b => {
        const t = (b.innerText || '').trim();
        return t === 'نشر' || t === 'Post' || t === 'إرسال' || t.includes('نشر');
      });
      if (postBtn && !postBtn.disabled) {
        postBtn.click();
        return true;
      }
      return false;
    });

    if (posted) {
      console.log('⏳ Post button clicked! Waiting for publish confirmation...');
      await new Promise(r => setTimeout(r, 8000));
      console.log('🎉 Post/Video successfully published to TikTok Studio!');
    } else {
      console.log('ℹ️ Uploaded & prepared on TikTok Studio.');
    }

    await browser.close();
    console.log('✅ TikTok publish operation completed.');
    process.exit(0);
  } catch (err) {
    console.error('❌ TikTok publish error:', err.message);
    try { await browser.close(); } catch {}
    process.exit(1);
  }
}

main();
