"""Mock meta-bridge — an in-process stand-in for the Node bridge (Phase 1).

Implements the bridge HTTP contract (owner spec §20) with the stdlib server:
  POST /v1/messages/send     (honors shadow → would_send=true, no delivery)
  GET  /v1/health
  GET  /v1/sessions
  POST /v1/messages/react
  POST /v1/messages/read
  POST /v1/messages/media
  GET  /v1/media/{id}?channel=
  GET  /v1/messages/{id}?channel=

Behaviors are configurable per test: response status overrides, delay for
read-timeout simulation, session state, and token enforcement. Every request
is recorded for assertions.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockBridge:
    def __init__(self, *, token: str = "test-bridge-token",
                 session_state: str = "CONNECTED", delay_seconds: float = 0.0,
                 send_status: int = 200, send_response: dict | None = None):
        self.token = token
        self.session_state = session_state
        self.delay_seconds = delay_seconds
        self.send_status = send_status
        self.send_response = send_response or {}
        self.requests: list[dict] = []
        self.media: dict[str, bytes] = {}
        self._counter = 0
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _next_id(self, prefix: str) -> str:
        with self._lock:
            self._counter += 1
            n = self._counter
        return f"{prefix}-{n}"

    # ---- request capture -------------------------------------------------
    def _record(self, method: str, path: str, body) -> None:
        with self._lock:
            self.requests.append({"method": method, "path": path,
                                  "body": body})

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"  # keep-alive safe for requests

            def log_message(self, *a):  # noqa: A003 — silence test noise
                pass

            def _json(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                return (self.headers.get("X-Bridge-Token") or "") == outer.token

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                if not length:
                    return {}
                try:
                    return json.loads(self.rfile.read(length).decode())
                except (ValueError, UnicodeDecodeError):
                    return {}

            def do_GET(self):  # noqa: N802
                outer._record("GET", self.path, None)
                if not self._authorized():
                    return self._json(403, {"error": "unauthorized"})
                if self.path.startswith("/v1/health"):
                    return self._json(200, {"ok": True, "bridge": "mock"})
                if self.path.startswith("/v1/sessions"):
                    return self._json(200, {"sessions": {
                        "whatsapp": {"state": outer.session_state,
                                     "transport": "baileys"},
                        "facebook": {"state": outer.session_state,
                                     "transport": "private"},
                        "instagram": {"state": outer.session_state,
                                      "transport": "realtime"},
                    }})
                if self.path.startswith("/v1/media/"):
                    media_id = self.path.split("/")[3].split("?")[0]
                    data = outer.media.get(media_id)
                    if data is None:
                        return self._json(404, {"error": "no media"})
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                return self._json(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802
                body = self._read_body()
                outer._record("POST", self.path, body)
                if not self._authorized():
                    return self._json(403, {"error": "unauthorized"})
                if outer.delay_seconds:
                    time.sleep(outer.delay_seconds)
                if self.path == "/v1/messages/send":
                    if outer.send_status != 200:
                        return self._json(
                            outer.send_status, {"error": "injected failure"})
                    shadow = bool(body.get("shadow"))
                    resp = {"accepted": True,
                            "external_message_id": outer._next_id("wamid"),
                            "status": "sent", "would_send": shadow}
                    resp.update(outer.send_response)
                    return self._json(200, resp)
                if self.path in ("/v1/messages/react", "/v1/messages/read"):
                    return self._json(200, {"accepted": True})
                if self.path == "/v1/messages/media":
                    media_id = outer._next_id("media")
                    raw = base64.b64decode(
                        (body or {}).get("data_base64") or "")
                    outer.media[media_id] = raw
                    return self._json(200, {"media_id": media_id})
                return self._json(404, {"error": "not found"})

        return Handler
