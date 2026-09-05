"""Test bridge voice intake and auto-transcription in the coordinator pipeline."""

from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock, patch

from amancore.channels.bridge_envelope import normalize_envelope
from amancore.channels.canonical import InboundMessage


class TestBridgeVoiceIntake(unittest.TestCase):
    def test_voice_envelope_normalization(self):
        sample_audio = b"OggS\x00\x02mock_audio_bytes"
        b64_audio = base64.b64encode(sample_audio).decode("ascii")

        raw_envelope = {
            "channel": "whatsapp",
            "event_type": "message.received",
            "external_message_id": "wamid.VOICE123",
            "account_id": "primary",
            "sender": {"external_id": "967770000000", "name": "Omar"},
            "timestamp": "2026-09-05T01:00:00Z",
            "message": {
                "type": "audio",
                "text": "",
                "media": {
                    "base64": b64_audio,
                    "mime": "audio/ogg; codecs=opus",
                    "size": len(sample_audio),
                },
            },
            "metadata": {"transport": "baileys"},
        }

        evt = normalize_envelope(raw_envelope)
        self.assertEqual(evt.event_type, "message.received")
        self.assertEqual(evt.channel, "whatsapp")
        self.assertEqual(evt.payload["message_type"], "audio")
        self.assertIsNotNone(evt.payload.get("media"))
        self.assertEqual(evt.payload["media"]["base64"], b64_audio)

        inbound_msg = InboundMessage.from_event(evt)
        self.assertEqual(inbound_msg.channel, "whatsapp")
        self.assertEqual(inbound_msg.message_type, "audio")
        self.assertEqual(inbound_msg.external_user_id, "967770000000")
        self.assertEqual(inbound_msg.media.get("base64"), b64_audio)

    @patch("amancore.voice.processor.VoiceNoteProcessor.transcribe")
    def test_coordinator_voice_auto_transcription(self, mock_transcribe):
        mock_transcribe.return_value = "أريد تصميم وبرمجة موقع لشركتنا"

        sample_audio = b"OggS\x00\x02test_audio_data"
        b64_audio = base64.b64encode(sample_audio).decode("ascii")

        inbound_msg = InboundMessage(
            channel="whatsapp",
            external_message_id="wamid.VOICE999",
            external_user_id="967770000000",
            text="",
            name="Omar",
            message_type="audio",
            media={
                "base64": b64_audio,
                "mime": "audio/ogg; codecs=opus",
            },
        )

        coordinator = MagicMock()
        recorded = []

        def mock_record(**kwargs):
            recorded.append(kwargs)

        coordinator.message_recorder = mock_record
        coordinator.crm.find_lead_by_identity.return_value = {
            "lead_id": "lead_123",
            "opt_out": 0,
            "consent_at": "2026-09-01",
        }
        coordinator.handover.can_send_ai.return_value = True
        coordinator.intent_router.classify_domain.return_value = "sales"
        coordinator.sales_agent.process_message.return_value = {"reply": "أهلاً بك! نسعد بخدمتك..."}
        coordinator.requirements_service = None
        coordinator.conversation = None
        coordinator._cir_decide.return_value = {"price_request": False, "decision": "continue", "entity": None, "temporal": None}
        coordinator._queue_reply = MagicMock()
        coordinator.memory.get_or_create.return_value = {"lead_id": "lead_123", "facts": {}, "working_memory": {}}
        coordinator.lang.detect.return_value = "ar"
        coordinator._recent_history.return_value = ""

        from amancore.channels.coordinator import MessageCoordinator
        result = MessageCoordinator._process_inbound(coordinator, inbound_msg)

        mock_transcribe.assert_called_once()
        call_args = mock_transcribe.call_args
        self.assertEqual(call_args[0][0], sample_audio)

        coordinator.sales_agent.process_message.assert_called_once()
        sent_text = coordinator.sales_agent.process_message.call_args[0][1]
        self.assertEqual(sent_text, "أريد تصميم وبرمجة موقع لشركتنا")

        self.assertTrue(len(recorded) > 0)
        self.assertEqual(recorded[0]["body"], "🎤 أريد تصميم وبرمجة موقع لشركتنا")



    @patch("amancore.voice.processor.VoiceNoteProcessor.transcribe")
    def test_coordinator_voice_empty_transcription_fallback(self, mock_transcribe):
        mock_transcribe.return_value = ""  # Silent or corrupted audio

        sample_audio = b"OggS\x00\x02silent_audio"
        b64_audio = base64.b64encode(sample_audio).decode("ascii")

        inbound_msg = InboundMessage(
            channel="whatsapp",
            external_message_id="wamid.SILENT1",
            external_user_id="967770000000",
            text="",
            name="Omar",
            message_type="audio",
            media={
                "base64": b64_audio,
                "mime": "audio/ogg; codecs=opus",
            },
        )

        coordinator = MagicMock()
        coordinator.crm.find_lead_by_identity.return_value = {
            "lead_id": "lead_123",
            "opt_out": 0,
            "consent_at": "2026-09-01",
        }
        coordinator.handover.can_send_ai.return_value = True
        coordinator.intent_router.classify_domain.return_value = "sales"
        coordinator.sales_agent.process_message.return_value = {"reply": "أهلاً بك! لم أتمكن من سماع التسجيل..."}
        coordinator.requirements_service = None
        coordinator.conversation = None
        coordinator._cir_decide.return_value = {"price_request": False, "decision": "continue", "entity": None, "temporal": None}
        coordinator._queue_reply = MagicMock()
        coordinator.memory.get_or_create.return_value = {"lead_id": "lead_123", "facts": {}, "working_memory": {}}
        coordinator.lang.detect.return_value = "ar"
        coordinator._recent_history.return_value = ""

        from amancore.channels.coordinator import MessageCoordinator
        MessageCoordinator._process_inbound(coordinator, inbound_msg)

        # Verified fallback prompt passed to sales_agent
        coordinator.sales_agent.process_message.assert_called_once()
        sent_text = coordinator.sales_agent.process_message.call_args[0][1]
        self.assertIn("أرسل العميل تسجيلاً صوتياً لم يتضمن كلاماً واضحاً", sent_text)

if __name__ == "__main__":
    unittest.main()
