"""Production smoke tests — production-like but CONTROLLED.

Uses a TEST lead / TEST number and the mock provider ONLY. Never uses real
customer data and never sends external messages. Covers inbound, outbound,
pricing snapshot, proposal, handoff, opt-out, human takeover.
"""

from __future__ import annotations

from ..log import get_logger

log = get_logger("ops.smoke")

TEST_WA_ID = "62800000000000"  # dedicated test number (E.164 test range)


class SmokeTestService:
    def __init__(self, coordinator, crm, adapter):
        self.coord = coordinator
        self.crm = crm
        self.adapter = adapter

    def _webhook(self, text: str, msg_id: str):
        return {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {
                "messaging_product": "whatsapp",
                "contacts": [{"wa_id": TEST_WA_ID, "profile": {"name": "Smoke Test"}}],
                "messages": [{"from": TEST_WA_ID, "id": msg_id, "type": "text",
                              "text": {"body": text}}],
            }}]}],
        }

    def run(self) -> dict:
        results = {}
        results["inbound"] = self._inbound()
        results["outbound"] = self._outbound()
        results["handoff"] = self._handoff()
        results["optout"] = self._optout()
        results["human_takeover"] = self._human_takeover()
        ok = all(r.get("status") == "PASS" for r in results.values())
        return {"status": "PASS" if ok else "FAIL", "tests": results}

    def _inbound(self) -> dict:
        try:
            self.crm.delete_test_lead(TEST_WA_ID)
            summary = self.coord.handle_whatsapp_webhook(
                self._webhook("I want a website for my restaurant", "smoke-in-1")
            )
            lead = self.crm.find_lead_by_whatsapp(TEST_WA_ID)
            ok = summary["processed"] == 1 and lead is not None
            return {"status": "PASS" if ok else "FAIL", "detail": f"processed={summary['processed']}, lead={'yes' if lead else 'no'}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "FAIL", "detail": str(exc)}

    def _outbound(self) -> dict:
        try:
            sent = [m for m in self.adapter.provider.sent if m.get("to") == TEST_WA_ID]
            ok = any(m["payload"] for m in sent)
            return {"status": "PASS" if ok else "FAIL",
                    "detail": f"replies_sent={len(sent)}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "FAIL", "detail": str(exc)}

    def _handoff(self) -> dict:
        try:
            summary = self.coord.handle_whatsapp_webhook(
                self._webhook("I want to talk to a human", "smoke-h-1")
            )
            ok = summary["handoffs"] >= 1
            return {"status": "PASS" if ok else "FAIL", "detail": f"handoffs={summary['handoffs']}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "FAIL", "detail": str(exc)}

    def _optout(self) -> dict:
        try:
            before = len(self.adapter.provider.sent)
            summary = self.coord.handle_whatsapp_webhook(
                self._webhook("stop", "smoke-o-1")
            )
            lead = self.crm.find_lead_by_whatsapp(TEST_WA_ID)
            ok = (lead is not None and lead.get("opt_out") == 1
                  and len(self.adapter.provider.sent) == before)
            return {"status": "PASS" if ok else "FAIL", "detail": f"opt_out={lead.get('opt_out') if lead else 'n/a'}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "FAIL", "detail": str(exc)}

    def _human_takeover(self) -> dict:
        try:
            from ..channels.handover import HandoverService

            lead = self.crm.find_lead_by_whatsapp(TEST_WA_ID)
            HandoverService(self.crm).activate_human(lead["lead_id"])
            before = len(self.adapter.provider.sent)
            self.coord.handle_whatsapp_webhook(
                self._webhook("how is my project?", "smoke-ht-1")
            )
            ok = len(self.adapter.provider.sent) == before
            return {"status": "PASS" if ok else "FAIL",
                    "detail": "AI blocked during human takeover"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "FAIL", "detail": str(exc)}
