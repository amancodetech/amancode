#!/usr/bin/env node
'use strict';

// Facebook Session Management CLI (Phase 3).
//
// Usage:
//   node scripts/fb-session.js status
//   node scripts/fb-session.js import <file_path_or_json_string>
//   node scripts/fb-session.js clear

const fs = require('node:fs');
const path = require('node:path');

const dataDir = process.env.BRIDGE_DATA_DIR ||
  path.join(__dirname, '..', '..', '..', 'bridge_data');
const sessionDir = path.join(dataDir, 'facebook_session');
const appStateFile = path.join(sessionDir, 'appstate.json');

const cmd = process.argv[2] || 'status';

function showStatus() {
  console.log(`📁 Facebook Session Directory: ${sessionDir}`);
  if (!fs.existsSync(appStateFile)) {
    console.log('❌ Status: AUTH_REQUIRED (appstate.json does not exist)');
    console.log('\n💡 To import a session, run:');
    console.log('   node scripts/fb-session.js import <path_to_appstate.json>');
    return;
  }
  try {
    const raw = fs.readFileSync(appStateFile, 'utf8');
    const parsed = JSON.parse(raw);
    const count = Array.isArray(parsed) ? parsed.length : Object.keys(parsed).length;
    console.log(`✅ Status: AppState exists (${count} cookies / session entries)`);
  } catch (err) {
    console.log(`⚠️ Status: Corrupted appstate.json (${err.message})`);
  }
}

function importSession(target) {
  if (!target) {
    console.error('Error: please provide a file path or JSON string to import.');
    process.exit(1);
  }
  let content = target;
  if (fs.existsSync(target)) {
    content = fs.readFileSync(target, 'utf8');
  }
  try {
    const parsed = JSON.parse(content);
    fs.mkdirSync(sessionDir, { recursive: true });
    fs.writeFileSync(appStateFile, JSON.stringify(parsed, null, 2), 'utf8');
    console.log(`✅ Successfully imported Facebook appstate to: ${appStateFile}`);
  } catch (err) {
    console.error(`❌ Failed to parse JSON: ${err.message}`);
    process.exit(1);
  }
}

function clearSession() {
  if (fs.existsSync(appStateFile)) {
    fs.unlinkSync(appStateFile);
    console.log('🗑️ Facebook session removed.');
  } else {
    console.log('ℹ️ No Facebook session file found.');
  }
}

if (cmd === 'status') showStatus();
else if (cmd === 'import') importSession(process.argv[3]);
else if (cmd === 'clear') clearSession();
else {
  console.log('Unknown command. Use: status | import <file> | clear');
}
