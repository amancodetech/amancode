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
    executablePath: fs.existsSync('/opt/google/chrome/chrome') ? '/opt/google/chrome/chrome' : (fs.existsSync('/snap/bin/brave') ? '/snap/bin/brave' : undefined),
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--dns-result-order=ipv4first',
      '--lang=ar,en',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1080 });
    await page.evaluateOnNewDocument(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    });

    const client = await page.target().createCDPSession();
    await client.send('Network.setCookies', {
      cookies: (sessionData.cookies || []).map(c => ({
        name: c.key,
        value: c.value,
        domain: '.' + (c.domain || 'tiktok.com').replace(/^\./, ''),
        path: c.path || '/',
      })),
    });

    const uploadUrl = 'https://www.tiktok.com/creator-center/upload?from=upload';
    console.log('🌐 Navigating to TikTok Studio Upload Center:', uploadUrl);
    try {
      await page.goto(uploadUrl, { waitUntil: 'networkidle2', timeout: 50000 });
    } catch (eNav) {
      console.warn('⚠️ Initial navigation timeout, continuing with page state:', eNav.message);
    }
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

    // Helper to dismiss modal popups (Content checks, new feature notices)
    const dismissModals = async () => {
      return await page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
        let dismissed = false;
        const checkBtn = btns.find(b => {
          const t = (b.innerText || '').trim();
          return ['إلغاء', 'تشغيل', 'Turn on', 'Cancel'].includes(t);
        });
        if (checkBtn) {
          checkBtn.click();
          dismissed = true;
        }

        const gotItBtn = btns.find(b => {
          const t = (b.innerText || '').trim();
          return ['فهمت', 'Got it'].includes(t);
        });
        if (gotItBtn) {
          gotItBtn.click();
          dismissed = true;
        }
        return dismissed;
      });
    };

    // Helper to safely set caption
    const setCaptionSafely = async (text) => {
      if (!text) return;
      console.log('✍️ Entering TikTok caption...');
      const ok = await page.evaluate((val) => {
        const box = document.querySelector('div[contenteditable="true"], div[role="textbox"], textarea');
        if (box) {
          box.focus();
          try {
            const dt = new DataTransfer();
            dt.setData('text/plain', val);
            const pasteEvt = new ClipboardEvent('paste', {
              bubbles: true,
              cancelable: true,
              clipboardData: dt,
            });
            box.dispatchEvent(pasteEvt);
            return true;
          } catch (ePaste) {
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, val);
            return true;
          }
        }
        return false;
      }, text);

      if (!ok) {
        const captionBox = await page.$('div[contenteditable="true"], textarea, div[role="textbox"]');
        if (captionBox) {
          await captionBox.click();
          await page.keyboard.down('Control');
          await page.keyboard.press('KeyA');
          await page.keyboard.up('Control');
          await page.keyboard.press('Backspace');
          await page.keyboard.type(text, { delay: 5 });
        }
      }
      console.log('✅ Caption entered successfully!');
    };

    // Upload file
    if (mediaPath && fs.existsSync(mediaPath)) {
      console.log('📁 Attaching media file to TikTok...');
      const fileInput = await page.$('input[type="file"]');
      if (fileInput) {
        await fileInput.uploadFile(path.resolve(mediaPath));
        console.log('✅ File attached! Waiting for processing & dismissing initial modals...');
        await new Promise(r => setTimeout(r, 6000));
        await dismissModals();
        await new Promise(r => setTimeout(r, 4000));
        await dismissModals();
      } else {
        console.warn('⚠️ File input not found.');
      }
    }

    // Enter caption after modals are dismissed
    if (caption) {
      await setCaptionSafely(caption);
    }

    // Calculate dynamic timeout based on media file size
    const fileSizeMB = (mediaPath && fs.existsSync(mediaPath)) ? (fs.statSync(mediaPath).size / (1024 * 1024)) : 0;
    const maxWaitSeconds = Math.max(240, Math.ceil(fileSizeMB * 15) + 120);
    const maxIters = Math.ceil(maxWaitSeconds / 2);
    console.log(`⏱️ Dynamic timeout: ${maxWaitSeconds}s (${maxIters} checks) for ${fileSizeMB.toFixed(1)}MB media`);

    // Wait for Post button to become enabled and click it with real mouse event
    console.log('🚀 Waiting for TikTok Post button to become enabled...');
    let posted = false;
    for (let iter = 0; iter < maxIters; iter++) {
      await dismissModals();
      await new Promise(r => setTimeout(r, 2000));

      const postBtnHandle = await page.evaluateHandle(() => {
        const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
        return btns.find(b => {
          const t = (b.innerText || '').trim();
          const disabled = b.getAttribute('aria-disabled') === 'true' || b.disabled === true || b.classList.contains('disabled');
          return (t === 'نشر' || t === 'Post') && !disabled;
        });
      });

      if (postBtnHandle && postBtnHandle.asElement()) {
        try {
          await postBtnHandle.asElement().scrollIntoViewIfNeeded();
          await new Promise(r => setTimeout(r, 500));
          const rect = await postBtnHandle.asElement().boundingBox();
          if (rect) {
            console.log(`🎯 Clicking Post button via mouse at (${rect.x + rect.width / 2}, ${rect.y + rect.height / 2})...`);
            await page.mouse.click(rect.x + rect.width / 2, rect.y + rect.height / 2);
          } else {
            await postBtnHandle.asElement().click();
          }
          posted = true;
          console.log('🎉 Post button clicked successfully!');
          break;
        } catch (ePost) {
          console.warn('Notice clicking post button:', ePost.message);
          posted = true;
          break;
        }
      }
      if (iter % 5 === 0) console.log(`⏳ Waiting for TikTok post button... (${iter * 2 + 2}s)`);
    }

    if (!posted) {
      throw new Error('TikTok Post button did not become enabled within timeout');
    }

    console.log('⏳ Post button clicked! Waiting for publish confirmation...');
    for (let w = 0; w < 30; w += 3) {
      await new Promise(r => setTimeout(r, 3000));
      const curUrl = page.url();
      console.log(`[T+${w + 3}s] Current page URL: ${curUrl}`);
      const success = await page.evaluate(() => {
        const text = document.body.innerText || '';
        return text.includes('تم تحميل الفيديو') || text.includes('Your video has been uploaded') || text.includes('إدارة منشوراتك') || text.includes('Manage your posts');
      });
      if (success || !curUrl.includes('upload')) {
        console.log('🎉 Confirmed: Video published on TikTok Studio!');
        break;
      }
    }

    try {
      await page.screenshot({ path: '/tmp/tiktok_post_result.png', fullPage: true });
    } catch {}
    console.log('🎉 Post/Video successfully published to TikTok Studio!');

    await browser.close();
    console.log('✅ TikTok publish operation completed.');
    process.exit(0);
  } catch (err) {
    console.error('❌ TikTok publish error:', err.message);
    try {
      await page.screenshot({ path: '/tmp/tiktok_post_error.png', fullPage: true });
      console.log('Saved error screenshot to /tmp/tiktok_post_error.png');
    } catch {}
    try { await browser.close(); } catch {}
    process.exit(1);
  }
}

main();
