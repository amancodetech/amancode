'use strict';
// Tiny HTTP router over node:http — no framework dependency.

const { BridgeError } = require('./errors');
const log = require('./log');

const MAX_BODY = 10 * 1024 * 1024; // 10 MB media uploads

class Router {
  constructor() {
    this.routes = [];
  }

  // method, pattern like "/v1/messages/:id"
  add(method, pattern, handler) {
    const parts = pattern.split('/').filter(Boolean);
    this.routes.push({ method, parts, handler, pattern });
  }

  get(p, h) { this.add('GET', p, h); }
  post(p, h) { this.add('POST', p, h); }

  match(method, pathname) {
    const segs = pathname.split('/').filter(Boolean);
    for (const r of this.routes) {
      if (r.method !== method) continue;
      if (r.parts.length !== segs.length) continue;
      const params = {};
      let ok = true;
      for (let i = 0; i < r.parts.length; i++) {
        if (r.parts[i].startsWith(':')) {
          params[r.parts[i].slice(1)] = decodeURIComponent(segs[i]);
        } else if (r.parts[i] !== segs[i]) {
          ok = false; break;
        }
      }
      if (ok) return { handler: r.handler, params };
    }
    return null;
  }
}

function readBody(req, limit = MAX_BODY) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) {
        reject(new BridgeError('body too large', 'invalid_request', 413));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function sendJson(res, status, payload) {
  const data = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(data),
  });
  res.end(data);
}

module.exports = { Router, readBody, sendJson, MAX_BODY };
