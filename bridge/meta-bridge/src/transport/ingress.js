'use strict';
// Durable ingress spool: every normalized inbound event is written to disk
// first, then forwarded to AmanCore /bridge/inbound with the ingress token.
// Ack (HTTP 2xx with accepted=true) deletes the spool file; anything else
// retries with backoff. Survives bridge restarts.

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const log = require('../core/log');

class IngressForwarder {
  constructor(config) {
    this.config = config;
    this.spoolDir = config.spoolDir;
    fs.mkdirSync(this.spoolDir, { recursive: true });
    this._queue = [];
    this._active = 0;
    this._stopping = false;
    this._timer = null;
    this._loadSpool();
  }

  _loadSpool() {
    let files = [];
    try {
      files = fs.readdirSync(this.spoolDir).filter(f => f.endsWith('.json')).sort();
    } catch { /* first run */ }
    for (const f of files) {
      try {
        const env = JSON.parse(fs.readFileSync(path.join(this.spoolDir, f), 'utf8'));
        this._queue.push({ file: f, envelope: env, attempts: 0 });
      } catch (err) {
        log.error('corrupt spool file', { file: f, error: err.message });
      }
    }
    if (files.length) log.info('spool restored', { pending: files.length });
  }

  enqueue(envelope) {
    const id = crypto.randomUUID();
    const file = `${Date.now()}-${id}.json`;
    fs.writeFileSync(
      path.join(this.spoolDir, file), JSON.stringify(envelope), 'utf8');
    this._queue.push({ file, envelope, attempts: 0 });
    log.info('ingress enqueued', { file, channel: envelope.channel });
    this._pump();
  }

  _pump() {
    if (this._stopping) return;
    while (this._active < this.config.ingressConcurrency &&
           this._queue.length > 0) {
      const item = this._queue.shift();
      this._active++;
      this._forward(item).finally(() => {
        this._active--;
        this._pump();
      });
    }
  }

  async _forward(item) {
    item.attempts++;
    try {
      const ack = await this._post(item.envelope);
      if (ack && ack.accepted) {
        this._done(item);
        return;
      }
      // AmanCore explicitly rejected (e.g. UNKNOWN_CHANNEL) — permanent
      log.error('ingress rejected by amancore', {
        file: item.file, ack, attempts: item.attempts,
      });
      this._done(item); // do not retry a 4xx ACK — it would never change
    } catch (err) {
      const retryIn = Math.min(
        this.config.ingressRetryBaseMs * 2 ** (item.attempts - 1),
        this.config.ingressRetryMaxMs);
      log.warn('ingress forward failed', {
        file: item.file, attempts: item.attempts,
        error: err.message, retry_ms: retryIn,
      });
      this._queue.push(item); // back of the queue, bounded by backoff below
      if (!this._timer) {
        this._timer = setTimeout(() => {
          this._timer = null; this._pump();
        }, retryIn);
        this._timer.unref();
      }
    }
  }

  _post(envelope) {
    const body = JSON.stringify(envelope);
    return new Promise((resolve, reject) => {
      const u = new URL('/bridge/inbound', this.config.amancoreBaseUrl);
      const req = http.request(u, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
          'X-Bridge-Token': this.config.ingressToken,
        },
        timeout: 10000,
      }, (res) => {
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => {
          let parsed = null;
          try { parsed = JSON.parse(Buffer.concat(chunks).toString()); }
          catch { /* non-json ack */ }
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(parsed);
          } else if (res.statusCode >= 500) {
            reject(new Error(`amancore ${res.statusCode} (retryable)`));
          } else {
            resolve(parsed); // 4xx: permanent rejection, handled above
          }
        });
      });
      req.on('timeout', () => req.destroy(new Error('amancore timeout')));
      req.on('error', reject);
      req.end(body);
    });
  }

  _done(item) {
    try { fs.unlinkSync(path.join(this.spoolDir, item.file)); }
    catch (err) { log.warn('spool unlink failed', { file: item.file }); }
  }

  depth() {
    return this._queue.length + this._active;
  }

  start() {
    this._stopping = false;
    this._pump();
  }

  async stop() {
    this._stopping = true;
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    // queued items stay on disk — durability across restarts
  }
}

module.exports = { IngressForwarder };
