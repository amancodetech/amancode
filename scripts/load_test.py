"""LOAD-601 — measured synthetic load harness (plan §20). In-process edition.

Boots an ISOLATED server (fresh DB, port 8011) inside THIS process with a
mock LLM at the mandated profiles (0.2s / 3s / hard-timeout), drives signed
webhooks through a concurrency ramp, writes the mandatory report to
docs/audit/LOAD_REPORT_raw_<profile>.json, then force-exits (runtime keeps
non-daemon helper threads alive otherwise).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)

PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"


def _env(key: str) -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def machine_baseline() -> dict:
    mem_kb = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            mem_kb = int(line.split()[1])
            break
    return {"nproc": os.cpu_count(), "ram_mb": mem_kb // 1024}


class _R:
    text = "رد وهمي مقيس لاختبار الحمل"


class FakeProvider:
    def __init__(self, latency):
        self.latency = latency

    def complete(self, messages, **kw):
        if self.latency is None:
            raise TimeoutError("mock LLM timeout")
        time.sleep(self.latency)
        return _R()


def boot(profile: str):
    """In-process isolated server on daemon threads. Returns nothing —
    sampler uses os.getpid()."""
    os.environ["DATABASE_PATH"] = "storage/_load_test.db"
    dbfile = ROOT / "storage" / "_load_test.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(dbfile) + suffix).unlink(missing_ok=True)

    print("[boot] importing runtime…", flush=True)
    from amancore.channels import coordinator as coord_mod
    from amancore.channels.webhook_server import (
        WebhookRequestHandler, build_runtime,
    )

    latency = {"fast": 0.2, "slow": 3.0}.get(profile)
    coord_mod.MessageCoordinator._quote_drafter = lambda self: FakeProvider(latency)
    print("[boot] build_runtime…", flush=True)
    runtime = build_runtime(ROOT)
    print("[boot] runtime ready", flush=True)

    from http.server import ThreadingHTTPServer

    class H(WebhookRequestHandler):
        pass

    H.runtime = runtime
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for _ in range(40):
        try:
            if urllib.request.urlopen(f"{BASE}/health", timeout=1).status == 200:
                print("[boot] healthy", flush=True)
                return
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise RuntimeError("server failed health")


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(_env("WHATSAPP_APP_SECRET").encode(),
                                body, hashlib.sha256).hexdigest()


def send_signed(wa: str, text: str, timeout: float = 30):
    body = json.dumps({"object": "whatsapp_business_account", "entry": [{
        "changes": [{"value": {"messages": [
            {"from": wa, "id": f"wamid.L.{wa}.{time.time_ns()}",
             "timestamp": str(int(time.time())), "type": "text",
             "text": {"body": text}}]}}]}]}).encode()
    req = urllib.request.Request(
        f"{BASE}/webhook/whatsapp", data=body,
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": sign(body)})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return r.status, time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        e.read()
        return e.code, time.perf_counter() - t0
    except Exception:  # noqa: BLE001
        return 0, time.perf_counter() - t0


def rss_mb(pid: int) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def nthreads(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("Threads:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return xs[k]


def run_load(per_phase: int, profile: str) -> dict:
    pid = os.getpid()
    ramp = [1, 5, 10, 20]
    latencies: list[float] = []
    errors = total = 0
    peak_threads = 0
    mem: list[float] = []
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            mem.append(rss_mb(pid))
            nonlocal_dummy = nthreads(pid)
            if nonlocal_dummy > peak["t"]:
                peak["t"] = nonlocal_dummy
            time.sleep(1)

    peak = {"t": 0}
    threading.Thread(target=sampler, daemon=True).start()

    run_tag = int(time.time()) % 100000
    phase_marks = []
    baseline_tp = None
    for conc in ramp:
        results: list[tuple[int, float]] = []

        def burst(wid):
            for j in range(per_phase):
                st, dt = send_signed(f"906{run_tag}{wid:02d}{j:03d}", f"حمل {wid}-{j}")
                results.append((st, dt))

        t0 = time.perf_counter()
        ths = [threading.Thread(target=burst, args=(c,)) for c in range(1, conc + 1)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(120)
        dur = time.perf_counter() - t0
        latencies.extend(d for _, d in results)
        errors += sum(1 for s, _ in results if s != 200)
        total += len(results)
        tp = round(len(results) / dur, 2)
        mark = {"concurrency": conc, "msgs": len(results),
                "wall_s": round(dur, 2), "throughput_msg_s": tp}
        if baseline_tp is None:
            baseline_tp = tp
        elif tp < baseline_tp * 0.5:   # §20: stop at first degradation
            mark["degradation"] = True
            phase_marks.append(mark)
            break
        phase_marks.append(mark)

    lag = None
    try:
        import sqlite3
        from datetime import datetime

        con = sqlite3.connect(str(ROOT / "storage" / "_load_test.db"))
        row = con.execute("SELECT MIN(created_at) FROM message_outbox"
                          " WHERE status IN ('queued','processing')").fetchone()
        con.close()
        if row and row[0]:
            lag = round(time.time() - datetime.fromisoformat(row[0]).timestamp(), 1)
    except Exception:  # noqa: BLE001
        pass

    stop.set(); time.sleep(0.2)
    return {
        "profile_mock_llm": profile,
        "tested_load": total,
        "p50_latency_s": round(pct(latencies, 50), 3),
        "p95_latency_s": round(pct(latencies, 95), 3),
        "p99_latency_s": round(pct(latencies, 99), 3),
        "error_rate_pct": round(100 * errors / max(1, total), 2),
        "max_concurrent_workers_observed": peak["t"],
        "memory_trend_mb": {"start": round(mem[0], 1) if mem else 0,
                            "peak": round(max(mem), 1) if mem else 0,
                            "end": round(mem[-1], 1) if mem else 0},
        "outbox_lag_s": lag,
        "ramp": phase_marks,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="fast",
                    choices=["fast", "slow", "timeout"])
    ap.add_argument("--per-phase", type=int, default=8)
    args = ap.parse_args()

    print("machine baseline:", machine_baseline(), flush=True)
    boot(args.profile)
    rep = run_load(args.per_phase, args.profile)
    out = ROOT / "docs" / "audit" / f"LOAD_REPORT_raw_{args.profile}.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print("WROTE", out.name, flush=True)
    print(json.dumps({k: v for k, v in rep.items() if k != "ramp"},
                     ensure_ascii=False), flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
