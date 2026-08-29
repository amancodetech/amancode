'use strict';
// In-memory metrics counters (spec §36). No external dependency —
// scrape-ready via a future /v1/metrics if needed.

const counters = new Map();

function incr(name, channel) {
  const key = `${channel || '_global'}.${name}`;
  counters.set(key, (counters.get(key) || 0) + 1);
}

function snapshot() {
  return Object.fromEntries(
    [...counters.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

function reset() {
  counters.clear();
}

module.exports = { incr, snapshot, reset };
