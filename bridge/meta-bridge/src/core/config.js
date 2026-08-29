'use strict';
// meta-bridge configuration — env-driven, fail-fast on missing secrets.

const path = require('node:path');

function required(name) {
  const v = process.env[name];
  if (!v) {
    throw new Error(`meta-bridge: missing required env ${name}`);
  }
  return v;
}

function bool(name, dflt = false) {
  const v = process.env[name];
  if (v === undefined || v === '') return dflt;
  return ['1', 'true', 'yes', 'on'].includes(v.toLowerCase());
}

const config = {
  port: Number(process.env.BRIDGE_PORT || 8765),
  host: process.env.BRIDGE_HOST || '127.0.0.1',

  // AmanCore -> bridge auth (checked on every request)
  bridgeToken: required('AMANCORE_BRIDGE_TOKEN'),
  // bridge -> AmanCore auth (sent on every /bridge/inbound call)
  ingressToken: required('BRIDGE_INGRESS_TOKEN'),

  // AmanCore webhook server base (ingress target)
  amancoreBaseUrl: process.env.AMANCORE_BASE_URL || 'http://127.0.0.1:8010',

  // durable spool for outbound ingress events (one JSON file per event)
  dataDir: process.env.BRIDGE_DATA_DIR ||
    path.join(__dirname, '..', '..', '..', 'bridge_data'),
  spoolDir: path.join(
    process.env.BRIDGE_DATA_DIR || path.join(__dirname, '..', '..', '..', 'bridge_data'),
    'ingress_spool'),

  // shadow mode: hold outbound deliveries, real sessions/normalization
  shadow: bool('BRIDGE_SHADOW', false),

  // which channels this instance serves
  channels: (process.env.BRIDGE_CHANNELS || 'whatsapp')
    .split(',').map(s => s.trim()).filter(Boolean),

  // session reconnect backoff (ms)
  reconnectBaseMs: Number(process.env.BRIDGE_RECONNECT_BASE_MS || 2000),
  reconnectMaxMs: Number(process.env.BRIDGE_RECONNECT_MAX_MS || 120000),

  // ingress forwarder
  ingressConcurrency: Number(process.env.BRIDGE_INGRESS_CONCURRENCY || 4),
  ingressRetryBaseMs: Number(process.env.BRIDGE_INGRESS_RETRY_MS || 1000),
  ingressRetryMaxMs: Number(process.env.BRIDGE_INGRESS_RETRY_MAX_MS || 60000),

  logLevel: process.env.BRIDGE_LOG_LEVEL || 'info',
};

module.exports = config;
