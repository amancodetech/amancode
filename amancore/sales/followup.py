"""Follow-up planning — planning only, no external send."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

TIMING = {1: 2, 2: 5, 3: 10, "reengage": 30}
STOP_STATUSES = {"won", "lost"}


class FollowupEngine:
    def plan(self, lead: dict, attempt: int = 1, now: datetime | None = None) -> dict | None:
        if lead.get("status") in STOP_STATUSES or lead.get("opt_out"):
            return None
        if attempt > 3:
            return None
        now = now or datetime.now(timezone.utc)
        days = TIMING.get(attempt, TIMING[3])
        scheduled = (now + timedelta(days=days)).isoformat()
        return {
            "lead_id": lead.get("lead_id"),
            "scheduled_at": scheduled,
            "reason": f"followup attempt {attempt}",
            "template_type": "followup",
            "status": "planned",
        }
