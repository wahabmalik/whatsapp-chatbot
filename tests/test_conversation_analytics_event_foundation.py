from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch


_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "https://example.test",
    "EVOLUTION_INSTANCE_NAME": "instance",
    "EVOLUTION_API_KEY": "evolution-key",
    "ACCESS_TOKEN": "token",
    "APP_SECRET": "secret",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test-key",
    "RECIPIENT_WAID": "15551234567",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "ESCALATION_KEYWORDS": "human",
}


class ConversationAnalyticsEventFoundationTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        from app import create_app

        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self._env.stop()

    @staticmethod
    def _inbound_payload(text: str = "need human help") -> dict:
        return {
            "key": {
                "fromMe": False,
                "id": "msg-analytics-1",
                "remoteJid": "15551234567@s.whatsapp.net",
            },
            "message": {"conversation": text},
        }

    def test_stage_events_emit_with_schema_stability(self):
        class _Channel:
            def send(self, _data, **_kwargs):
                return {
                    "ok": True,
                    "status": "sent",
                    "error": None,
                    "deferred": False,
                    "operator_review_flagged": False,
                    "operator_review_reason": None,
                }

        with patch("app.utils.whatsapp_utils.find_faq_answer", return_value=None), patch(
            "app.utils.whatsapp_utils._generate_reply_result",
            return_value={
                "ok": True,
                "reply_text": "Handled",
                "status": "success",
                "confidence": 0.2,
                "error_code": None,
                "metadata": {},
            },
        ), patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=_Channel()), patch(
            "app.utils.whatsapp_utils.append_review_artifact",
            return_value=(True, None),
        ):
            response = self.client.post("/webhook", json=self._inbound_payload())

        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            from app.services.conversation_analytics import get_analytics_event_buffer

            events = get_analytics_event_buffer(self.app).get_all()

        stages = {item.get("stage") for item in events}
        self.assertTrue(
            {"inbound_receive", "ai_outcome", "escalation_flag", "outbound_outcome"}.issubset(stages)
        )

        required_keys = {
            "event_version",
            "event_type",
            "stage",
            "timestamp",
            "correlation_id",
            "conversation_key",
            "user_key",
            "outcome_status",
            "details",
        }
        for item in events:
            self.assertTrue(required_keys.issubset(item.keys()))
            self.assertEqual(item.get("event_version"), "1.0")
            self.assertTrue(str(item.get("correlation_id")))
            self.assertTrue(str(item.get("conversation_key", "")).startswith("conv_"))
            self.assertTrue(str(item.get("user_key", "")).startswith("usr_"))

        serialized = json.dumps(events)
        self.assertNotIn("15551234567", serialized)

    def test_analytics_endpoint_exposes_escalation_trend_signal(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.app.config["ANALYTICS_EVENT_STORE_PATH"] = os.path.join(
                tmp_dir,
                "analytics-events.jsonl",
            )

            class _Channel:
                def send(self, _data, **_kwargs):
                    return {
                        "ok": True,
                        "status": "sent",
                        "error": None,
                        "deferred": False,
                        "operator_review_flagged": False,
                        "operator_review_reason": None,
                    }

            with patch("app.utils.whatsapp_utils.find_faq_answer", return_value=None), patch(
                "app.utils.whatsapp_utils._generate_reply_result",
                return_value={
                    "ok": True,
                    "reply_text": "Handled",
                    "status": "success",
                    "confidence": 0.1,
                    "error_code": None,
                    "metadata": {},
                },
            ), patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=_Channel()), patch(
                "app.utils.whatsapp_utils.append_review_artifact",
                return_value=(True, None),
            ):
                response = self.client.post("/webhook", json=self._inbound_payload("please connect human"))

            self.assertEqual(response.status_code, 200)

            api_response = self.client.get("/api/analytics/events?limit=50")
            self.assertEqual(api_response.status_code, 200)
            payload = api_response.get_json() or {}

            summary = payload.get("summary") or {}
            self.assertIn("total_events", summary)
            self.assertIn("escalation_events", summary)
            self.assertIn("escalation_flagged_count", summary)
            self.assertIn("escalation_flag_rate", summary)
            self.assertGreaterEqual(summary.get("escalation_flagged_count", 0), 1)
            self.assertGreater(summary.get("escalation_flag_rate", 0.0), 0.0)

    def test_analytics_events_survive_in_memory_buffer_clear(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.app.config["ANALYTICS_EVENT_STORE_PATH"] = os.path.join(
                tmp_dir,
                "analytics-events.jsonl",
            )

            class _Channel:
                def send(self, _data, **_kwargs):
                    return {
                        "ok": True,
                        "status": "sent",
                        "error": None,
                        "deferred": False,
                        "operator_review_flagged": False,
                        "operator_review_reason": None,
                    }

            with patch("app.utils.whatsapp_utils.find_faq_answer", return_value=None), patch(
                "app.utils.whatsapp_utils._generate_reply_result",
                return_value={
                    "ok": True,
                    "reply_text": "Handled",
                    "status": "success",
                    "confidence": 0.95,
                    "error_code": None,
                    "metadata": {},
                },
            ), patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=_Channel()), patch(
                "app.utils.whatsapp_utils.append_review_artifact",
                return_value=(False, None),
            ):
                response = self.client.post("/webhook", json=self._inbound_payload("hello"))

            self.assertEqual(response.status_code, 200)

            with self.app.app_context():
                from app.services.conversation_analytics import get_analytics_event_buffer

                get_analytics_event_buffer(self.app).clear()

            api_response = self.client.get("/api/analytics/events?limit=50")
            self.assertEqual(api_response.status_code, 200)
            payload = api_response.get_json() or {}
            events = payload.get("events") or []
            self.assertGreaterEqual(len(events), 1)

    def test_analytics_event_store_retention_cap_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.app.config["ANALYTICS_EVENT_STORE_PATH"] = os.path.join(
                tmp_dir,
                "analytics-events.jsonl",
            )
            self.app.config["ANALYTICS_EVENT_STORE_MAX_LINES"] = 3

            with self.app.app_context():
                from app.services.conversation_analytics import emit_analytics_event, get_recent_analytics_events

                for index in range(6):
                    emit_analytics_event(
                        self.app,
                        stage="escalation_flag",
                        correlation_id=f"corr-{index}",
                        user_id=f"user-{index}",
                        conversation_id=f"conv-{index}",
                        outcome_status="flagged",
                        details={"seq": index},
                    )

                recent = get_recent_analytics_events(self.app, limit=50)

            store_path = self.app.config["ANALYTICS_EVENT_STORE_PATH"]
            with open(store_path, encoding="utf-8") as handle:
                lines = [line for line in handle.read().splitlines() if line.strip()]

            self.assertEqual(len(lines), 3)
            self.assertEqual(len(recent), 3)
            details_seq = [event.get("details", {}).get("seq") for event in recent]
            self.assertEqual(details_seq, [5, 4, 3])


if __name__ == "__main__":
    unittest.main()
