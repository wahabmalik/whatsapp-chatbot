from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
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
    "ANALYTICS_RETENTION_DAYS": "7",
}


class AnalyticsReportingApiContractTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        from app import create_app

        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self._env.stop()

    def _set_operator_role(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

    @staticmethod
    def _write_event(handle, *, stage: str, timestamp: datetime, outcome_status: str, correlation_id: str, details: dict | None = None) -> None:
        payload = {
            "event_version": "1.0",
            "event_type": f"conversation.{stage}",
            "stage": stage,
            "timestamp": timestamp.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "correlation_id": correlation_id,
            "conversation_key": f"conv_{correlation_id}",
            "user_key": "usr_contract",
            "outcome_status": outcome_status,
            "details": details or {},
        }
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _seed_events(self, path: str, *, include_old_event: bool = True, event_count: int = 0) -> None:
        now = datetime.now(timezone.utc)
        with open(path, "w", encoding="utf-8") as handle:
            self._write_event(
                handle,
                stage="inbound_receive",
                timestamp=now,
                outcome_status="received",
                correlation_id="current-1",
            )
            self._write_event(
                handle,
                stage="escalation_flag",
                timestamp=now,
                outcome_status="flagged",
                correlation_id="current-1",
            )
            self._write_event(
                handle,
                stage="outbound_outcome",
                timestamp=now,
                outcome_status="sent",
                correlation_id="current-1",
                details={"latency_ms": 45},
            )
            if include_old_event:
                old_timestamp = now - timedelta(days=14)
                self._write_event(
                    handle,
                    stage="inbound_receive",
                    timestamp=old_timestamp,
                    outcome_status="received",
                    correlation_id="expired-1",
                )
                self._write_event(
                    handle,
                    stage="outbound_outcome",
                    timestamp=old_timestamp,
                    outcome_status="failure",
                    correlation_id="expired-1",
                    details={"latency_ms": 999},
                )
            for index in range(event_count):
                self._write_event(
                    handle,
                    stage="outbound_outcome",
                    timestamp=now,
                    outcome_status="sent",
                    correlation_id=f"bulk-{index}",
                    details={"latency_ms": 10 + (index % 5)},
                )

    def test_summary_endpoint_requires_operator_access(self):
        response = self.client.get("/api/analytics/summary", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/operator/access", response.headers.get("Location", ""))

    def test_summary_endpoint_returns_stable_contract(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = os.path.join(tmp_dir, "conversation_analytics_events.jsonl")
            self.app.config["ANALYTICS_EVENT_STORE_PATH"] = store_path
            self._set_operator_role()
            self._seed_events(store_path)

            response = self.client.get("/api/analytics/summary")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json() or {}
            self.assertTrue(payload.get("ok"))

            required_keys = {
                "volume_trend",
                "escalation_trend",
                "delivery_breakdown",
                "latency_summary",
                "latency_trend",
                "coverage_hours",
                "insufficient_data",
                "window_days",
                "retention_days",
                "generated_at",
            }
            self.assertTrue(required_keys.issubset(payload.keys()))
            self.assertEqual(payload["window_days"], 7)
            self.assertEqual(payload["retention_days"], 7)
            self.assertIsInstance(payload["insufficient_data"], bool)

            volume_trend = payload["volume_trend"]
            escalation_trend = payload["escalation_trend"]
            delivery_breakdown = payload["delivery_breakdown"]
            latency_summary = payload["latency_summary"]
            latency_trend = payload["latency_trend"]

            self.assertEqual(len(volume_trend), 7)
            self.assertEqual(len(escalation_trend), 7)
            self.assertEqual(delivery_breakdown["success"], 1)
            self.assertEqual(delivery_breakdown["retry"], 0)
            self.assertEqual(delivery_breakdown["failure"], 0)
            self.assertGreaterEqual(latency_summary["p50_ms"], 0)
            self.assertGreaterEqual(latency_summary["p95_ms"], latency_summary["p50_ms"])
            self.assertGreaterEqual(latency_summary["p99_ms"], latency_summary["p95_ms"])
            self.assertEqual(len(latency_trend), 7)

            self.assertEqual(sum(item["count"] for item in volume_trend), 1)
            self.assertEqual(sum(item["count"] for item in escalation_trend), 1)

    def test_summary_endpoint_excludes_expired_events_and_prune_helper_removes_them(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = os.path.join(tmp_dir, "conversation_analytics_events.jsonl")
            self.app.config["ANALYTICS_EVENT_STORE_PATH"] = store_path
            self._set_operator_role()
            self._seed_events(store_path, include_old_event=True)

            from app.services.conversation_analytics import get_analytics_summary, prune_analytics_event_store

            summary = get_analytics_summary(self.app)
            self.assertEqual(sum(item["count"] for item in summary["volume_trend"]), 1)
            self.assertEqual(sum(item["count"] for item in summary["escalation_trend"]), 1)
            self.assertEqual(summary["delivery_breakdown"]["failure"], 0)

            pruned = prune_analytics_event_store(self.app)
            self.assertGreaterEqual(pruned, 2)

            with open(store_path, encoding="utf-8") as handle:
                remaining = [line for line in handle.read().splitlines() if line.strip()]

            self.assertEqual(len(remaining), 3)

    def test_summary_endpoint_meets_sla_for_10000_events(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = os.path.join(tmp_dir, "conversation_analytics_events.jsonl")
            self.app.config["ANALYTICS_EVENT_STORE_PATH"] = store_path
            self._set_operator_role()
            self._seed_events(store_path, include_old_event=False, event_count=10000)

            start = time.perf_counter()
            response = self.client.get("/api/analytics/summary")
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(elapsed_ms, 500.0)


if __name__ == "__main__":
    unittest.main()
