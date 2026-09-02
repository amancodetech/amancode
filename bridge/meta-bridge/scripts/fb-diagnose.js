#!/usr/bin/env node
'use strict';
// Diagnose the restored facebook session: which API classes work?
const fs = require('node:fs');
const path = require('node:path');

const config = require('../src/core/config');
const appstateFile = path.join(config.dataDir, 'facebook_session', 'appstate.json');
const appState = JSON.parse(fs.readFileSync(appstateFile, 'utf8'));

const mod = require('ws3-fca');
const login = mod.login || mod.default || mod;

login({ appState }, { logLevel: 'silent' }, (err, api) => {
  if (err) { console.error('restore failed:', JSON.stringify(err.error || err.message)); process.exit(1); }
  const uid = api.getCurrentUserID();
  console.log('userID (from cookies):', uid);

  const timeout = (ms, label) => new Promise((_, rej) =>
    setTimeout(() => rej(new Error(label + ' timeout')), ms));

  (async () => {
    // 1. getUserInfo — basic authenticated read
    try {
      const info = await Promise.race([
        new Promise((res, rej) => api.getUserInfo([uid], (e, r) => e ? rej(e) : res(r))),
        timeout(15000, 'getUserInfo'),
      ]);
      console.log('getUserInfo: OK →', JSON.stringify(Object.keys(info || {})));
      console.log('name:', info?.[uid]?.name);
    } catch (e) { console.log('getUserInfo: FAIL →', e.message || JSON.stringify(e.error).slice(0, 120)); }

    // 2. getThreadList — Messenger read
    try {
      const threads = await Promise.race([
        new Promise((res, rej) => api.getThreadList(3, null, ['INBOX'], (e, r) => e ? rej(e) : res(r))),
        timeout(15000, 'getThreadList'),
      ]);
      console.log('getThreadList: OK →', (threads || []).length, 'threads');
      for (const t of (threads || []).slice(0, 3)) {
        console.log('  thread:', t.threadID, '|', String(t.snippet || '').slice(0, 30));
      }
    } catch (e) { console.log('getThreadList: FAIL →', e.message || JSON.stringify(e.error).slice(0, 120)); }

    // 3. sendMessage — the failing op (to self)
    try {
      const info = await Promise.race([
        new Promise((res, rej) => api.sendMessage(
          { body: '[diagnostic] session probe' }, uid, (e, r) => e ? rej(e) : res(r)),
        ),
        timeout(20000, 'sendMessage'),
      ]);
      console.log('sendMessage: OK →', JSON.stringify(info).slice(0, 80));
    } catch (e) { console.log('sendMessage: FAIL →', e.message || JSON.stringify(e.error).slice(0, 120)); }

    try { api.stop(); } catch { /* noop */ }
    process.exit(0);
  })();
});
