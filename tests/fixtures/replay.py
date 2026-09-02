"""Reusable Webhook Replay & Idempotency Testing Utilities."""

from __future__ import annotations

import concurrent.futures
from typing import Any
from amancore.requirements.service import RequirementsService
from amancore.crm.service import CRMService
from amancore.storage.db import open_database


def replay_message(
    ril: RequirementsService,
    lead_id: str,
    message: str,
    source_message_id: str = "wamid.replay.canonical",
    conversation_id: str = "conv_replay_canonical",
    times: int = 5,
    concurrent_exec: bool = False,
    db_path: Any = None,
    schema_path: Any = None,
) -> list[dict[str, Any]]:
    """Replay an inbound message N times sequentially or concurrently to verify idempotency."""
    if not concurrent_exec or not db_path or not schema_path:
        # Sequential execution
        results = []
        for _ in range(times):
            res = ril.process_message(
                lead_id=lead_id,
                message=message,
                source_message_id=source_message_id,
                conversation_id=conversation_id,
            )
            results.append(res)
        return results

    # Concurrent replay with thread-isolated DB connections
    def worker_turn():
        db_w = open_database(db_path, schema_path)
        crm_w = CRMService(db_w)
        ril_w = RequirementsService(crm_w)
        try:
            return ril_w.process_message(
                lead_id=lead_id,
                message=message,
                source_message_id=source_message_id,
                conversation_id=conversation_id,
            )
        finally:
            db_w.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(times, 8)) as executor:
        futures = [executor.submit(worker_turn) for _ in range(times)]
        return [f.result() for f in futures]


def assert_replay_idempotent(results: list[dict[str, Any]]) -> None:
    """Assert that subsequent replays did not inflate requirement counts."""
    if len(results) < 2:
        return
    canonical_total = results[0]["total_requirements_count"]
    for idx, r in enumerate(results[1:], start=2):
        if r.get("new_requirements_count", 0) != 0:
            raise AssertionError(
                f"IDEMPOTENCY VIOLATION: Replay turn #{idx} created new requirements!"
            )
        if r.get("total_requirements_count") != canonical_total:
            raise AssertionError(
                f"IDEMPOTENCY VIOLATION: Replay turn #{idx} total requirements count mismatch ({r.get('total_requirements_count')} != {canonical_total})"
            )
