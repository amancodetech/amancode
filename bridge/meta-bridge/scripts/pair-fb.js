#!/usr/bin/env node
'use strict';
// Facebook pairing with FULL 2FA support — browser-emulation login flow
// (same mechanism as fca-unofficial: lgnrnd form → checkpoint approvals_code
// → session jar → appstate).
//
// Usage:
//   node scripts/pair-fb.js
//       prompts: email, password, and the 6-digit 2FA code when challenged
//
//   node scripts/pair-fb.js --totp "xxxx xxxx xxxx xxxx"
//       generates the 2FA code automatically from the TOTP secret key
//       (Facebook → Settings → Two-factor → Authentication app → "Can't scan?" → setup key)
//
//   node scripts/pair-fb.js --import <cookies.json>
//       cookie-import mode (unchanged)
//
// Credentials are prompted (hidden), used ONCE, NEVER stored.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const readline = require('node:readline');
const axios = require('axios');
const { CookieJar } = require('tough-cookie');

const config = require('../src/core/config');
const sessionDir = path.join(config.dataDir, 'facebook_session');
const appstateFile = path.join(sessionDir, 'appstate.json');

const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

function ask(question, hidden) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin, output: process.stdout, terminal: true,
    });
    if (hidden) {
      rl.question(question, (a) => {
        rl.close();
        process.stdout.write('\r\x1b[K');
        resolve(a);
      });
      rl.stdoutMuted = true;
      rl._writeToOutput = function _writeToOutput(s) {
        if (rl.stdoutMuted && s.includes(question)) rl.output.write(question);
        else if (rl.stdoutMuted) rl.output.write('*');
        else rl.output.write(s);
      };
    } else {
      rl.question(question, (a) => { rl.close(); resolve(a); });
    }
  });
}

// ---- RFC 6238 TOTP (no dependency) -----------------------------------------

function totp(secretBase32, step = 30, digits = 6) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const clean = secretBase32.replace(/[\s-]/g, '').toUpperCase();
  let bits = '';
  for (const ch of clean) {
    const idx = alphabet.indexOf(ch);
    if (idx === -1) continue;
    bits += idx.toString(2).padStart(5, '0');
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  const key = Buffer.from(bytes);
  const counter = Math.floor(Date.now() / 1000 / step);
  const buf = Buffer.alloc(8);
  buf.writeUInt32BE(Math.floor(counter / 2 ** 32), 0);
  buf.writeUInt32BE(counter % 2 ** 32, 4);
  const hmac = crypto.createHmac('sha1', key).update(buf).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code = ((hmac[offset] & 0x7f) << 24 | hmac[offset + 1] << 16 |
    hmac[offset + 2] << 8 | hmac[offset + 3]) % 10 ** digits;
  return String(code).padStart(digits, '0');
}

// ---- minimal facebook client (browser-emulation login) ---------------------

function mkClient() {
  const jar = new CookieJar();
  const client = axios.create({
    maxRedirects: 'error',   // we handle redirects manually (checkpoint logic)
    validateStatus: () => true,
    headers: { 'User-Agent': UA, 'Accept-Language': 'en_US' },
  });
  client.interceptors.request.use((cfg) => {
    cfg.headers.Cookie = jar.getCookieStringSync(cfg.url || '');
    return cfg;
  });
  client.interceptors.response.use((res) => {
    const setCookies = res.headers['set-cookie'] || [];
    for (const c of setCookies) {
      try { jar.setCookieSync(c, res.config.url); } catch { /* ignore */ }
    }
    return res;
  });
  return { client, jar };
}

function getFrom(html, start, end) {
  const i = html.indexOf(start);
  if (i === -1) return '';
  return html.slice(i + start.length,
    html.indexOf(end, i + start.length));
}

function parseFormInputs(html) {
  const form = {};
  const re = /<input[^>]*>/g;
  for (const tag of html.match(re) || []) {
    const name = getFrom(tag, 'name="', '"');
    const value = getFrom(tag, 'value="', '"');
    if (name && value) form[name] = value;
  }
  return form;
}

function jarToAppState(jar) {
  const now = new Date().toISOString();
  return jar.getCookiesSync('https://www.facebook.com', { allPaths: true })
    .map((c) => ({
      key: c.key, value: c.value,
      domain: `.${c.domain.replace(/^\./, '')}`,
      path: c.path || '/',
      hostOnly: c.hostOnly, creation: now, lastAccessed: now,
    }));
}

async function credentialsLogin(email, password, totpSecret) {
  const { client, jar } = mkClient();
  const base = 'https://www.facebook.com';
  const nextURL = `${base}/checkpoint/?next=${encodeURIComponent(base + '/home.php')}`;

  console.log('[1/4] fetching login page…');
  const page = await client.get(`${base}/`);
  let html = page.data;
  // JS-injected cookies (facebook inlines them as "_js_" literals)
  for (const chunk of html.split('"_js_').slice(1)) {
    const cookieData = JSON.parse(`"${getFrom(chunk, '', ']')}"`);
    try {
      jar.setCookieSync(
        `${cookieData[0]}=${cookieData[1]}; Domain=.facebook.com; Path=/`,
        base);
    } catch { /* ignore */ }
  }

  const form = parseFormInputs(html);
  console.log('    captured form fields:', Object.keys(form).join(', ') || 'NONE');
  if (!form.lgnrnd) {
    // fallback: the dedicated login page carries lgnrnd
    const lp = await client.get(`${base}/login/`);
    html = lp.data;
    for (const chunk of html.split('"_js_').slice(1)) {
      const cookieData = JSON.parse(`"${getFrom(chunk, '', ']')}"`);
      try {
        jar.setCookieSync(
          `${cookieData[0]}=${cookieData[1]}; Domain=.facebook.com; Path=/`,
          base);
      } catch { /* ignore */ }
    }
    Object.assign(form, parseFormInputs(html));
    form.lgnrnd = getFrom(html, 'name="lgnrnd" value="', '"');
  }
  form.email = email;
  form.pass = password;
  form.lgnjs = String(Math.floor(Date.now() / 1000));
  form.locale = 'en_US';
  form.timezone = '240';
  form.default_persistent = '0';

  console.log('[2/4] submitting credentials…');
  const loginRes = await client.post(
    `${base}/login/device-based/regular/login/?login_attempt=1&lwv=110`,
    new URLSearchParams(form).toString(),
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });

  const body = String(loginRes.data);
  const loc = loginRes.headers.location || '';
  const fbRedirect = getFrom(body, 'window.location.replace("', '")')
    || getFrom(body, '"redirect":"', '"').replace(/\\\//g, '/');
  if (!loc && fbRedirect) {
    return { jar, appState: jarToAppState(jar), redirect: fbRedirect };
  }
  if (!loc && !fbRedirect) {
    // surface what facebook ACTUALLY said
    const title = getFrom(body, '<title>', '</title>');
    const errRow = getFrom(body, 'login_error', '</div>');
    const uiErr = (body.match(/data-xui-error="([^"]{3,120})"/) || [])[1];
    const arErr = (() => {
      try {
        const json = JSON.parse(body.replace(/^for \(;;\);/, ''));
        if (json.error) return JSON.stringify(json.error).slice(0, 200);
        if (json.payload?.errorSummary) return json.payload.errorSummary;
      } catch { /* not json */ }
      return null;
    })();
    throw new Error('facebook rejected the login — '
      + `title="${title.slice(0, 60)}" `
      + `error="${(uiErr || errRow?.slice(0, 120) || arErr || 'unknown').trim()}"`);
  }

  const target = loc || fbRedirect;
  if (!target.includes('/checkpoint/')) {
    return { jar, appState: jarToAppState(jar) };
  }

  // ---- 2FA challenge ----
  console.log('[2/4] 2FA challenge detected (checkpoint)…');
  const cpTarget = target.startsWith('http') ? target : base + target;
  const cp = await client.get(cpTarget);
  html = cp.data;
  const cpForm = parseFormInputs(html);
  const hasApprovals = html.includes('approvals_code');

  if (!hasApprovals) {
    throw new Error('checkpoint is NOT a 2FA code challenge — the account ' +
      'needs manual verification in the browser first (facebook.com → clear it), ' +
      'then re-run this script.');
  }

  let code;
  if (totpSecret) {
    code = totp(totpSecret);
    console.log(`[3/4] TOTP code generated: ${code}`);
  } else {
    code = await ask('Enter the 6-digit 2FA code: ');
  }
  if (!code) throw new Error('2FA code required');

  console.log('[3/4] submitting 2FA code…');
  cpForm.approvals_code = code;
  cpForm.page_id = '';
  cpForm.unrecognized = '';
  const submitURL = nextURL;
  const r1 = await client.post(submitURL,
    new URLSearchParams(cpForm).toString(),
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded',
      Referer: nextURL } });
  if (String(r1.data).includes('data-xui-error')) {
    const msg = getFrom(String(r1.data), 'data-xui-error="', '"');
    throw new Error(`invalid 2FA code${msg ? ` (${msg})` : ''} — try again`);
  }

  // second leg: "don't save device"
  const cpForm2 = parseFormInputs(r1.data);
  cpForm2.name_action_selected = 'dont_save';
  await client.post(submitURL,
    new URLSearchParams(cpForm2).toString(),
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded',
      Referer: nextURL } });

  const appState = jarToAppState(jar);
  return { jar, appState };
}

function loadDriver() {
  for (const name of ['ws3-fca', 'facebook-chat-api',
    '@xaviabot/fca-unofficial']) {
    try {
      const mod = require(name);
      return { name, login: mod.login || mod.default || mod };
    } catch { /* next */ }
  }
  console.error('no facebook driver installed');
  process.exit(1);
}

async function saveAndVerify(appState) {
  fs.mkdirSync(sessionDir, { recursive: true });
  fs.writeFileSync(appstateFile, JSON.stringify(appState, null, 2));
  console.log(`[4/4] appstate saved → ${appstateFile}`);

  // verify through the SAME driver the bridge uses
  const { login } = loadDriver();
  await new Promise((resolve, reject) => {
    login({ appState }, { logLevel: 'silent' }, (err, api) => {
      if (err) {
        console.error('driver verify FAILED:',
          typeof err.error === 'object' ? JSON.stringify(err.error)
            : (err.error || err.message));
        reject(err);
        return;
      }
      console.log('✓ verified by bridge driver — userID:',
        api.getCurrentUserID());
      try { api.stop(); } catch { /* noop */ }
      resolve();
    });
  });
}

async function doCredentials(totpSecret) {
  // env support (FB_EMAIL / FB_PASS / FB_TOTP) — also enables scripted runs
  const email = process.env.FB_EMAIL || await ask('Facebook email/phone: ');
  if (!email) { console.error('email required'); process.exit(1); }
  const password = process.env.FB_PASS || await ask('Password (hidden): ', true);
  if (!password) { console.error('password required'); process.exit(1); }
  if (!totpSecret && process.env.FB_TOTP) totpSecret = process.env.FB_TOTP;

  const { appState } = await credentialsLogin(email, password, totpSecret);
  await saveAndVerify(appState);
  console.log('\nNEXT: systemctl --user restart meta-bridge');
}

async function doImport(file) {
  const raw = fs.readFileSync(path.resolve(file), 'utf8');
  const arr = JSON.parse(raw);
  if (!Array.isArray(arr)) throw new Error('cookie file must be a JSON array');
  const keys = new Set(arr.map((c) => c.key || c.name));
  for (const k of ['c_user', 'xs', 'datr']) {
    if (!keys.has(k)) {
      console.error(`cookie file is missing critical cookie: ${k}`);
      process.exit(1);
    }
  }
  console.log(`[1/3] restoring session from ${file} (${arr.length} cookies)…`);
  const { login } = loadDriver();
  await new Promise((resolve, reject) => {
    login({ appState: arr }, { logLevel: 'silent' }, (err, api) => {
      if (err) {
        console.error('IMPORT FAILED:', typeof err.error === 'object'
          ? JSON.stringify(err.error) : (err.error || err.message));
        process.exit(1);
      }
      console.log('[2/3] logged in as user:', api.getCurrentUserID());
      fs.mkdirSync(sessionDir, { recursive: true });
      fs.writeFileSync(appstateFile, JSON.stringify(arr, null, 2));
      console.log(`[3/3] appstate saved → ${appstateFile}`);
      console.log('\nNEXT: systemctl --user restart meta-bridge');
      try { api.stop(); } catch { /* noop */ }
      resolve();
    });
  });
}

async function main() {
  const importIdx = process.argv.indexOf('--import');
  if (importIdx > -1) {
    const file = process.argv[importIdx + 1];
    if (!file) {
      console.log('Paste the Cookie-Editor export (JSON) then press Ctrl+D:');
      const chunks = [];
      for await (const chunk of process.stdin) chunks.push(chunk);
      file = '/tmp/opencode/fb-cookies.json';
      fs.writeFileSync(file, Buffer.concat(chunks).toString().trim());
      console.log(`(captured ${file})`);
    }
    await doImport(file);
    return;
  }

  const totpIdx = process.argv.indexOf('--totp');
  const totpSecret = totpIdx > -1 ? process.argv[totpIdx + 1] : null;

  console.log('=== Facebook pairing (browser-flow with 2FA) ===');
  console.log(`session → ${appstateFile}\n`);
  await doCredentials(totpSecret);
}

main().catch((err) => {
  console.error('\npairing failed:', err.message);
  process.exit(1);
});
