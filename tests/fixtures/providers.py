"""External Provider Test Doubles (Messaging, Payments, Storage)."""

from __future__ import annotations

from typing import Any


class FakeMessagingProvider:
    """Mock WhatsApp / Telegram / Messenger provider."""

    def __init__(self, channel: str = "whatsapp"):
        self.channel = channel
        self.sent_messages: list[dict[str, Any]] = []
        self.fail_mode: bool = False

    def send_message(self, recipient: str, text: str, **kwargs) -> dict[str, Any]:
        if self.fail_mode:
            raise RuntimeError(f"PROVIDER_FAILURE: Failed sending to {recipient} on {self.channel}")

        msg_record = {
            "channel": self.channel,
            "recipient": recipient,
            "text": text,
            "status": "sent",
            "provider_message_id": f"fake_prov_mid_{len(self.sent_messages) + 1}",
            "kwargs": kwargs,
        }
        self.sent_messages.append(msg_record)
        return msg_record

    def reset(self) -> None:
        self.sent_messages.clear()
        self.fail_mode = False


class FakePaymentProvider:
    """Mock Payment Gateway (Stripe, Midtrans, Mada)."""

    def __init__(self, gateway_name: str = "stripe"):
        self.gateway_name = gateway_name
        self.transactions: list[dict[str, Any]] = []
        self.fail_mode: bool = False

    def create_charge(self, amount: float, currency: str, customer_id: str) -> dict[str, Any]:
        if self.fail_mode:
            raise RuntimeError(f"PAYMENT_DECLINED: Payment provider {self.gateway_name} error")

        tx = {
            "gateway": self.gateway_name,
            "amount": amount,
            "currency": currency,
            "customer_id": customer_id,
            "charge_id": f"ch_fake_{len(self.transactions) + 1}",
            "status": "succeeded",
        }
        self.transactions.append(tx)
        return tx
