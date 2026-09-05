'use strict';
/**
 * Meta Multi-Platform Post Publisher (Facebook + Instagram)
 * Uses Meta Business Suite Composer & Reels Composer with stored session cookies.
 *
 * Usage:
 *   node scripts/meta-create-post.js --text "Your post text" --image "/path/to/media.mp4" --platform "all|facebook|instagram"
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

async function typeTextSafely(page, text) {
  if (!text) return;
  console.log('✍️ Entering post text line-by-line...');
  const box = await page.$('div[role="combobox"][contenteditable="true"], div[role="textbox"][contenteditable="true"], textarea, div[contenteditable="true"]');
  if (box) {
    await box.click();
    await new Promise(r => setTimeout(r, 500));
    const lines = text.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line) {
        await page.keyboard.type(line, { delay: 8 });
      }
      if (i < lines.length - 1) {
        await page.keyboard.down('Shift');
        await page.keyboard.press('Enter');
        await page.keyboard.up('Shift');
        await new Promise(r => setTimeout(r, 40));
      }
    }
    console.log('✅ Full text typed successfully!');
  } else {
    console.warn('⚠️ Textbox not found, trying active element fallback...');
    await page.keyboard.type(text, { delay: 8 });
  }
}

async function publishPost() {
  const { text, imagePath, platform } = parseArgs();

  if (!fs.existsSync(APP_STATE_PATH)) {
    console.error('❌ Error: appstate.json missing at', APP_STATE_PATH);
    process.exit(1);
  }

  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  const isVideo = Boolean(
    imagePath &&
    ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.m4v'].some(ext => imagePath.toLowerCase().endsWith(ext))
  );

  console.log('🌐 Launching browser to publish on Meta (FB / Instagram)...');
  console.log('📝 Platform:', platform);
  console.log('🎬 Media Type:', isVideo ? 'Video (Reels)' : (imagePath ? 'Image (Feed)' : 'Text Only'));
  console.log('📝 Text:', text ? text.slice(0, 80) + '...' : '(No text)');
  console.log('📁 Media:', imagePath || '(No media)');

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
    await page.setViewport({ width: 1440, height: 1080 });

    const client = await page.target().createCDPSession();
    await client.send('Network.setCookies', {
      cookies: appState.map(c => ({
        name: c.key,
        value: c.value,
        domain: '.' + (c.domain || 'facebook.com').replace(/^\./, ''),
        path: c.path || '/',
      })),
    });

    if (isVideo) {
      // -------------------------------------------------------------
      // VIDEO PUBLISHING VIA REELS COMPOSER (Facebook & Instagram Reels)
      // -------------------------------------------------------------
      const reelsUrl = `https://business.facebook.com/latest/reels_composer/?asset_id=${ASSET_ID}&business_id=${BUSINESS_ID}`;
      console.log('🌐 Navigating to Meta Reels Composer...');
      await page.goto(reelsUrl, { waitUntil: 'networkidle2', timeout: 45000 });
      await new Promise(r => setTimeout(r, 6000));

      console.log('🔍 Locating "إضافة فيديو" button...');
      const addVideoHandle = await page.evaluateHandle(() => {
        const btns = Array.from(document.querySelectorAll('div[role="button"], button'));
        return btns.find(b => (b.innerText || '').trim().includes('إضافة فيديو'));
      });

      if (!addVideoHandle || !addVideoHandle.asElement()) {
        throw new Error('Could not find "إضافة فيديو" button in Reels composer');
      }

      console.log('📁 Triggering file chooser for video upload...');
      const [fileChooser] = await Promise.all([
        page.waitForFileChooser({ timeout: 20000 }),
        addVideoHandle.asElement().click(),
      ]);

      await fileChooser.accept([path.resolve(imagePath)]);
      console.log('✅ Video attached! Typing caption...');

      // Type caption
      await typeTextSafely(page, text);

      // Wait for Next (التالي) button to become enabled (dynamically scaled to file size)
      const fileSizeMB = (imagePath && fs.existsSync(imagePath)) ? (fs.statSync(imagePath).size / (1024 * 1024)) : 0;
      const maxWaitSeconds = Math.max(240, Math.ceil(fileSizeMB * 15) + 120);
      console.log(`⏱️ Dynamic timeout: ${maxWaitSeconds}s for Reels video upload (${fileSizeMB.toFixed(1)}MB)`);
      console.log('⏳ Waiting for video upload & Next button to become enabled...');
      let nextReady = false;
      for (let sec = 0; sec < maxWaitSeconds; sec += 3) {
        await new Promise(r => setTimeout(r, 3000));
        const status = await page.evaluate(() => {
          const btns = Array.from(document.querySelectorAll('div[role="button"], button'));
          const next = btns.find(b => (b.innerText || '').trim() === 'التالي');
          if (!next) return { found: false };
          const disabled = next.getAttribute('aria-disabled') === 'true' || next.disabled === true;
          return { found: true, disabled };
        });

        if (status.found && !status.disabled) {
          nextReady = true;
          console.log(`✅ Next button enabled at ${sec + 3}s!`);
          break;
        }
        if (sec % 12 === 0) console.log(`⏳ Uploading video... (${sec + 3}s)`);
      }

      if (!nextReady) {
        throw new Error('Timeout waiting for Reels video upload to enable Next button');
      }

      // Step 1 -> Step 2
      console.log('➡️ Moving to Step 2 (Edit/Timeline)...');
      const nextBtn1 = await page.evaluateHandle(() => {
        return Array.from(document.querySelectorAll('div[role="button"], button')).find(b => (b.innerText || '').trim() === 'التالي');
      });
      if (nextBtn1 && nextBtn1.asElement()) {
        try {
          await nextBtn1.asElement().scrollIntoViewIfNeeded();
          const r1 = await nextBtn1.asElement().boundingBox();
          if (r1) {
            await page.mouse.click(r1.x + r1.width / 2, r1.y + r1.height / 2);
          } else {
            await nextBtn1.asElement().click();
          }
        } catch (e1) {
          console.warn('Notice clicking Next 1:', e1.message);
        }
      }

      // Wait for Step 2 to load & find Next button in Step 2
      console.log('⏳ Waiting for Step 2 (Timeline)...');
      let nextBtn2Handle = null;
      for (let s2 = 0; s2 < 15; s2++) {
        await new Promise(r => setTimeout(r, 1500));
        nextBtn2Handle = await page.evaluateHandle(() => {
          const btns = Array.from(document.querySelectorAll('div[role="button"], button'));
          return btns.find(b => {
            const t = (b.innerText || '').trim();
            const disabled = b.getAttribute('aria-disabled') === 'true' || b.disabled === true;
            return t === 'التالي' && !disabled;
          });
        });
        if (nextBtn2Handle && nextBtn2Handle.asElement()) {
          console.log(`✅ Step 2 Next button ready at ${s2 * 1.5}s!`);
          break;
        }
      }

      // Step 2 -> Step 3
      console.log('➡️ Moving to Step 3 (Share/Publish)...');
      if (nextBtn2Handle && nextBtn2Handle.asElement()) {
        try {
          await nextBtn2Handle.asElement().scrollIntoViewIfNeeded();
          const r2 = await nextBtn2Handle.asElement().boundingBox();
          if (r2) {
            await page.mouse.click(r2.x + r2.width / 2, r2.y + r2.height / 2);
          } else {
            await nextBtn2Handle.asElement().click();
          }
        } catch (e2) {
          console.warn('Notice clicking Next 2:', e2.message);
        }
      }
      await new Promise(r => setTimeout(r, 4000));

      // Step 3: Find and click the real Share (مشاركة) button in the bottom footer
      console.log('🚀 Looking for final Share (مشاركة) footer button...');
      let shared = false;
      for (let waitShare = 0; waitShare < 30; waitShare += 2) {
        // Remove any floating overlay icons that might block the footer button
        await page.evaluate(() => {
          document.querySelectorAll('[aria-label*="المساعد"], [aria-label*="AI"]').forEach(e => {
            const r = e.getBoundingClientRect();
            if (r.top > 800) e.style.display = 'none';
          });
        });

        const shareBtnHandle = await page.evaluateHandle(() => {
          const btns = Array.from(document.querySelectorAll('div[role="button"], button'));
          const matches = btns.filter(b => {
            const t = (b.innerText || '').trim();
            const disabled = b.getAttribute('aria-disabled') === 'true' || b.disabled === true;
            return (t === 'مشاركة' || t === 'Share') && !disabled;
          });
          // The actual action button is in the footer at the bottom of the page (top > 500px)
          // NOT the step breadcrumb tab at the top of the page (top ~ 80px)
          const footerBtn = matches.reverse().find(b => {
            const r = b.getBoundingClientRect();
            return r.top > 500 && r.width > 30;
          });
          return footerBtn || null;
        });

        if (shareBtnHandle && shareBtnHandle.asElement()) {
          try {
            await shareBtnHandle.asElement().scrollIntoViewIfNeeded();
            await new Promise(r => setTimeout(r, 500));
            const rShare = await shareBtnHandle.asElement().boundingBox();
            console.log('🎯 Found footer Share button at rect:', rShare);
            if (rShare) {
              console.log(`🎯 Clicking Share button via mouse at (${rShare.x + rShare.width / 2}, ${rShare.y + rShare.height / 2})...`);
              await page.mouse.click(rShare.x + rShare.width / 2, rShare.y + rShare.height / 2);
              await new Promise(r => setTimeout(r, 300));
            }
            await page.evaluate(el => el && el.click(), shareBtnHandle.asElement());
            shared = true;
            console.log('🎉 Share (مشاركة) button clicked successfully!');
            break;
          } catch (eShare) {
            console.warn('Notice clicking Share button:', eShare.message);
          }
        }
        await new Promise(r => setTimeout(r, 2000));
      }

      if (!shared) {
        throw new Error('Could not find enabled footer Share (مشاركة) button in Reels composer');
      }

      console.log('⏳ Waiting for publication to process and navigate...');
      let published = false;
      for (let w = 0; w < 45; w += 3) {
        await new Promise(r => setTimeout(r, 3000));
        const curUrl = page.url();
        console.log(`[T+${w + 3}s] Current page URL: ${curUrl}`);
        const toast = await page.evaluate(() => {
          const text = document.body.innerText || '';
          return text.includes('تم نشر') || text.includes('تمت مشاركة') || text.includes('جارٍ النشر') || text.includes('معالجة مقطع ريلز') || text.includes('تمت جدولة');
        });
        if (!curUrl.includes('reels_composer') || toast) {
          published = true;
          console.log('✅ Publication confirmed! Post published successfully!');
          break;
        }
      }

      if (!published) {
        throw new Error('Meta Reels: URL remained on reels_composer after Share click — post was not submitted');
      }

      // Click [ تم ] to close the "جارٍ معالجة مقطع ريلز" dialog if present
      try {
        console.log('⏳ Dismissing completion dialog with [ تم ]...');
        await page.evaluate(() => {
          const btns = Array.from(document.querySelectorAll('div[role="button"], button'));
          const done = btns.find(b => ['تم', 'Done', 'موافق', 'OK'].includes((b.innerText || '').trim()));
          if (done) done.click();
        });
        await new Promise(r => setTimeout(r, 3000));
      } catch (eDone) {
        console.warn('Notice dismissing done dialog:', eDone.message);
      }

      try {
        await page.screenshot({ path: '/tmp/meta_post_result.png', fullPage: true });
        console.log('Saved post screenshot to /tmp/meta_post_result.png');
      } catch {}
      console.log('🎉 Video Reel successfully published to Meta (Facebook & Instagram)!');

    } else {
      // -------------------------------------------------------------
      // IMAGE / TEXT POST PUBLISHING VIA STANDARD COMPOSER
      // -------------------------------------------------------------
      const composerUrl = `https://business.facebook.com/latest/composer/?asset_id=${ASSET_ID}&business_id=${BUSINESS_ID}`;
      console.log('🌐 Opening Meta Business Suite Composer...');
      await page.goto(composerUrl, { waitUntil: 'networkidle2', timeout: 45000 });
      await new Promise(r => setTimeout(r, 6000));

      if (imagePath && fs.existsSync(imagePath)) {
        console.log('📁 Attaching image file:', imagePath);
        const addBtnHandle = await page.evaluateHandle(() => {
          const btns = Array.from(document.querySelectorAll('div[role="button"], button'));
          return btns.find(b => {
            const t = b.innerText || '';
            return t.includes('إضافة') && (t.includes('صورة') || t.includes('فيديو'));
          });
        });

        if (addBtnHandle && addBtnHandle.asElement()) {
          const [fileChooser] = await Promise.all([
            page.waitForFileChooser({ timeout: 15000 }),
            addBtnHandle.asElement().click(),
          ]);
          await fileChooser.accept([path.resolve(imagePath)]);
          console.log('✅ Image attached via file chooser!');
        } else {
          const fileInput = await page.$('input[type=file]');
          if (fileInput) {
            await fileInput.uploadFile(path.resolve(imagePath));
            console.log('✅ Image attached via file input!');
          }
        }

        // Wait for upload progress to finish
        for (let waitSec = 0; waitSec < 30; waitSec += 3) {
          await new Promise(r => setTimeout(r, 3000));
          const stillUploading = await page.evaluate(() => !!document.querySelector('[role="progressbar"], progress'));
          if (!stillUploading) break;
        }
      }

      // Enter post text
      await typeTextSafely(page, text);
      await new Promise(r => setTimeout(r, 3000));

      // Wait for Publish button to become enabled
      console.log('🚀 Looking for enabled Publish button...');
      let published = false;
      for (let retry = 0; retry < 20; retry++) {
        const pubHandle = await page.evaluateHandle(() => {
          const btns = Array.from(document.querySelectorAll('[role=button], button, div[role=button]'));
          return btns.find(b => {
            const t = (b.innerText || '').trim();
            const disabled = b.disabled === true || b.getAttribute('aria-disabled') === 'true';
            return (t === 'نشر' || t === 'Publish' || t.startsWith('نشر على') || t.includes('نشر على')) && !disabled;
          });
        });

        if (pubHandle && pubHandle.asElement()) {
          const rPub = await pubHandle.asElement().boundingBox();
          if (rPub) {
            await page.mouse.click(rPub.x + rPub.width / 2, rPub.y + rPub.height / 2);
          } else {
            await pubHandle.asElement().click();
          }
          published = true;
          console.log('🎉 Clicked Publish button via real mouse event!');
          break;
        }
        await new Promise(r => setTimeout(r, 2000));
      }

      if (published) {
        console.log('⏳ Waiting for publishing confirmation...');
        await new Promise(r => setTimeout(r, 15000));
        try {
          await page.screenshot({ path: '/tmp/meta_post_result.png', fullPage: true });
        } catch {}
        console.log('🎉 Post successfully published to Meta (Facebook / Instagram)!');
      } else {
        throw new Error('Could not find enabled Publish button in standard composer');
      }
    }

    await browser.close();
    console.log('✅ Completed successfully.');
    process.exit(0);
  } catch (err) {
    console.error('❌ Error publishing post:', err.message);
    try {
      await page.screenshot({ path: '/tmp/meta_post_error.png', fullPage: true });
      console.log('Saved error screenshot to /tmp/meta_post_error.png');
    } catch {}
    try { await browser.close(); } catch {}
    process.exit(1);
  }
}

publishPost();
