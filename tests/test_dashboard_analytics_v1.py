from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


_BASE_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "test-token",
    "APP_SECRET": "test-secret",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
    "RECIPIENT_WAID": "15551234567",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "ANALYTICS_RETENTION_DAYS": "30",
}


class DashboardAnalyticsV1Tests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        from app import create_app

        self.app = create_app(config_name="testing")
        self.client = self.app.test_client()

    def tearDown(self):
        self._env.stop()

    def _set_operator_role(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

    def test_operator_dashboard_contains_analytics_section_with_summary_api_hook(self):
        self._set_operator_role()

        response = self.client.get("/operator", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("data-analytics-section", html)
        self.assertIn('data-analytics-summary-url="/api/analytics/summary"', html)
        self.assertIn("data-analytics-insufficient", html)

    def test_analytics_summary_reports_insufficient_data_for_less_than_24h_coverage(self):
        self._set_operator_role()

        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = os.path.join(tmp_dir, "conversation_analytics_events.jsonl")
            self.app.config["ANALYTICS_EVENT_STORE_PATH"] = store_path

            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            event = {
                "event_version": "1.0",
                "event_type": "conversation.outbound_outcome",
                "stage": "outbound_outcome",
                "timestamp": now,
                "correlation_id": "single-correlation",
                "conversation_key": "conv_single",
                "user_key": "usr_single",
                "outcome_status": "sent",
                "details": {"latency_ms": 42},
            }
            with open(store_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True) + "\n")

            response = self.client.get("/api/analytics/summary")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("insufficient_data"))
        self.assertIn("latency_trend", payload)


if __name__ == "__main__":
    unittest.main()
