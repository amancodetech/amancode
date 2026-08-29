#!/usr/bin/env node
'use strict';

// Instagram Session Management CLI (Phase 4).
//
// Usage:
//   node scripts/ig-session.js status
//   node scripts/ig-session.js import <file_path_or_json_string>
//   node scripts/ig-session.js clear

const fs = require('node:fs');
const path = require('node:path');

const dataDir = process.env.BRIDGE_DATA_DIR ||
  path.join(__dirname, '..', '..', '..', 'bridge_data');
const sessionDir = path.join(dataDir, 'instagram_session');
const sessionFile = path.join(sessionDir, 'session.json');

const cmd = process.argv[2] || 'status';

function showStatus() {
  console.log(`📁 Instagram Session Directory: ${sessionDir}`);
  if (!fs.existsSync(sessionFile)) {
    console.log('❌ Status: AUTH_REQUIRED (session.json does not exist)');
    console.log('\n💡 To import a session, run:');
    console.log('   node scripts/ig-session.js import <path_to_session.json>');
    return;
  }
  try {
    const raw = fs.readFileSync(sessionFile, 'utf8');
    const parsed = JSON.parse(raw);
    console.log(`✅ Status: Session file exists (keys: ${Object.keys(parsed).join(', ')})`);
  } catch (err) {
    console.log(`⚠️ Status: Corrupted session.json (${err.message})`);
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
    fs.writeFileSync(sessionFile, JSON.stringify(parsed, null, 2), 'utf8');
    console.log(`✅ Successfully imported Instagram session to: ${sessionFile}`);
  } catch (err) {
    console.error(`❌ Failed to parse JSON: ${err.message}`);
    process.exit(1);
  }
}

function clearSession() {
  if (fs.existsSync(sessionFile)) {
    fs.unlinkSync(sessionFile);
    console.log('🗑️ Instagram session removed.');
  } else {
    console.log('ℹ️ No Instagram session file found.');
  }
}

if (cmd === 'status') showStatus();
else if (cmd === 'import') importSession(process.argv[3]);
else if (cmd === 'clear') clearSession();
else {
  console.log('Unknown command. Use: status | import <file> | clear');
}
