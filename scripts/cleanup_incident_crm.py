"""2026-08-24 incident CRM cleanup — archive then purge load-test pollution.

Fake entities: leads created TODAY whose contact matches load-harness number
patterns (+ their conversations/messages/outbox links). Outbox ROWS ARE KEPT
(Meta appeal evidence). Dry-run by default; --apply performs deletions.
"""
import json, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "storage" / "aman_core.db"
ARCHIVE = ROOT / "backups" / f"incident-20260824-crm-pollution-{int(time.time())}.json"

PATTERNS = ("906%", "9050000%", "905100%")
DAY = "2026-08-24"

con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
where = "created_at >= ? AND (" + " OR ".join("contact_whatsapp LIKE ?" for _ in PATTERNS) + ")"
params = (DAY, *PATTERNS)

leads = con.execute(f"SELECT * FROM leads WHERE {where}", params).fetchall()
ids = [r["lead_id"] for r in leads]
print(f"fake leads identified: {len(ids)}")

def qmarks(xs): return ",".join("?" * len(xs))
archive = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "lead_ids": ids, "leads": [dict(r) for r in leads], "conversations": [],
           "channel_messages": []}
if ids:
    archive["conversations"] = [dict(r) for r in con.execute(
        f"SELECT * FROM conversations WHERE lead_id IN ({qmarks(ids)})", ids)]
    archive["channel_messages"] = [dict(r) for r in con.execute(
        f"SELECT * FROM channel_messages WHERE lead_id IN ({qmarks(ids)})", ids)]

ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"archived → {ARCHIVE.name} ({ARCHIVE.stat().st_size//1024} KB)")

if "--apply" not in sys.argv:
    print("DRY-RUN — rerun with --apply to purge"); raise SystemExit(0)

cur_total = 0
for sql, prms in [
    (f"DELETE FROM channel_messages WHERE lead_id IN ({qmarks(ids)})", ids),
    (f"DELETE FROM conversations WHERE lead_id IN ({qmarks(ids)})", ids),
    (f"DELETE FROM opportunities WHERE lead_id IN ({qmarks(ids)})", ids),
    (f"DELETE FROM research_results WHERE lead_id IN ({qmarks(ids)})", ids),
    (f"DELETE FROM leads WHERE lead_id IN ({qmarks(ids)})", ids),
]:
    cur = con.execute(sql, prms); cur_total += cur.rowcount; con.commit()
print(f"purged rows total: {cur_total}")

left = con.execute(f"SELECT COUNT(*) c FROM leads WHERE {where}", params).fetchone()["c"]
print(f"remaining matching leads: {left}")
con.close()
