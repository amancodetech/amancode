'use strict';
// Structured logging: every line is one JSON object (spec §35).

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

let minLevel = LEVELS.info;

function setLevel(name) {
  minLevel = LEVELS[name] ?? LEVELS.info;
}

function emit(level, msg, fields) {
  if (LEVELS[level] < minLevel) return;
  const rec = {
    ts: new Date().toISOString(),
    level,
    component: 'meta-bridge',
    msg,
    ...fields,
  };
  process.stdout.write(JSON.stringify(rec) + '\n');
}

module.exports = {
  setLevel,
  debug: (msg, fields) => emit('debug', msg, fields),
  info: (msg, fields) => emit('info', msg, fields),
  warn: (msg, fields) => emit('warn', msg, fields),
  error: (msg, fields) => emit('error', msg, fields),
};
