'use strict';
const puppeteer = require('puppeteer');
const fs = require('fs');

const APP_STATE_PATH = '/home/omar/Desktop/work/aman-core/bridge_data/facebook_session/appstate.json';
const IMAGE_PATH = '/home/omar/Desktop/work/aman-core/assets/amancode_user_cover.jpg';
const TARGET_PAGE_URL = 'https://web.facebook.com/profile.php?id=61593733289713';

async function debugCover() {
  const appState = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf8'));
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--window-size=1366,900'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1366, height: 900 });

  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('response', async resp => {
    if (resp.url().includes('graphql') && resp.request().method() === 'POST') {
      try {
        const text = await resp.text();
        if (text.includes('error') || text.includes('cover') || text.includes('photo')) {
          console.log('GRAPHQL RESP:', text.slice(0, 200));
        }
      } catch (e) {}
    }
  });

  const cookies = appState.map(c => ({
    name: c.key || c.name,
    value: c.value,
    domain: (c.domain || 'facebook.com').startsWith('.') ? c.domain : `.${c.domain}`,
    path: c.path || '/',
    httpOnly: c.httpOnly || false,
    secure: c.secure || false,
  }));
  await page.setCookie(...cookies);

  await page.goto(TARGET_PAGE_URL, { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));

  const buttons = await page.$$('div[role="button"]');
  for (const btn of buttons) {
    const label = await page.evaluate(el => (el.getAttribute('aria-label') || el.textContent || '').trim(), btn);
    if (label.includes('صورة غلاف') || label.includes('إضافة صورة غلاف') || label.includes('تعديل صورة الغلاف')) {
      console.log('Clicked cover button:', label);
      await btn.click();
      await new Promise(r => setTimeout(r, 2000));
      break;
    }
  }

  const menuItems = await page.$$('div[role="menuitem"]');
  for (const item of menuItems) {
    const txt = await page.evaluate(el => el.textContent || '', item);
    if (txt.includes('تحميل صورة')) {
      console.log('Clicking "تحميل صورة"');
      const [fileChooser] = await Promise.all([
        page.waitForFileChooser({ timeout: 6000 }),
        item.click(),
      ]);
      await fileChooser.accept([IMAGE_PATH]);
      break;
    }
  }

  console.log('Waiting 12s for image upload...');
  await new Promise(r => setTimeout(r, 12000));

  console.log('Clicking Save Changes...');
  const saveBtns = await page.$$('div[role="button"], button');
  for (const s of saveBtns) {
    const txt = await page.evaluate(el => (el.textContent || el.getAttribute('aria-label') || '').trim(), s);
    if (txt === 'حفظ التغييرات' || txt.includes('حفظ التغييرات')) {
      console.log('Found and clicked Save Changes:', txt);
      await s.click();
      break;
    }
  }

  console.log('Waiting 20s for save response...');
  await new Promise(r => setTimeout(r, 20000));
  await browser.close();
}

debugCover();
