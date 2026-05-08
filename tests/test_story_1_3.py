"""Tests for Story 1.3: correlation logging and observability baseline."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch


FULL_REQUIRED_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "OPENAI_API_KEY": "sk-test-key",
    "RECIPIENT_WAID": "15551234567",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
}


class Story13CorrelationIdTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        from app import create_app

        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def _signature(self, payload: str) -> str:
        digest = hmac.new(
            b"supersecret", msg=payload.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"

    def test_verify_rejection_generates_correlation_id(self):
        response = self.client.get("/webhook")

        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertTrue(payload.get("correlation_id"))
        self.assertEqual(payload.get("reason"), "missing_params")
        self.assertEqual(response.headers.get("X-Request-ID"), payload.get("correlation_id"))

    def test_verify_rejection_uses_inbound_correlation_id(self):
        response = self.client.get(
            "/webhook",
            headers={"X-Request-ID": "req-123"},
        )

        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertEqual(payload.get("correlation_id"), "req-123")
        self.assertEqual(response.headers.get("X-Request-ID"), "req-123")

    def test_successful_webhook_post_sets_x_request_id_header(self):
        payload = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "contacts": [
                                        {
                                            "wa_id": "15551234567",
                                            "profile": {"name": "Tester"},
                                        }
                                    ],
                                    "messages": [
                                        {"id": "wamid-1", "text": {"body": "hello"}}
                                    ],
                                }
                            }
                        ]
                    }
                ],
            }
        )

        with patch(
            "app.views.process_whatsapp_message",
            return_value={
                "from": "15551234567",
                "message_id": "wamid-1",
                "agent": "Ops",
                "input_text": "hello",
                "reply_text": "reply",
                "status": "sent",
                "error": None,
            },
        ):
            response = self.client.post(
                "/webhook",
                data=payload,
                content_type="application/json",
                headers={"X-Hub-Signature-256": self._signature(payload)},
            )

        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("X-Request-ID")
        self.assertIsInstance(request_id, str)
        self.assertTrue(request_id)


class Story13LoggingSanitizationTests(unittest.TestCase):
    def test_sanitize_text_masks_sensitive_material(self):
        from app.services.observability import sanitize_text

        raw = (
            "Authorization=Bearer abcdef123456 "
            "openai_api_key=sk-abcDEF1234567890 "
            "verify_token=mytoken "
            "from=15551234567"
        )

        sanitized = sanitize_text(raw)

        self.assertNotIn("abcdef123456", sanitized)
        self.assertNotIn("sk-abcDEF1234567890", sanitized)
        self.assertNotIn("mytoken", sanitized)
        self.assertNotIn("15551234567", sanitized)
        self.assertIn("[REDACTED]", sanitized)
        self.assertRegex(sanitized, r"\+?\d{1,4}\.\.\.4567")

    def test_sanitize_text_masks_modern_openai_key_variants(self):
        from app.services.observability import sanitize_text

        raw = (
            "OPENAI_API_KEY=sk-proj-Abcdef_1234-LongerSegment "
            "backup=sk-live_ABC-12345678"
        )

        sanitized = sanitize_text(raw)

        self.assertNotIn("sk-proj-Abcdef_1234-LongerSegment", sanitized)
        self.assertNotIn("sk-live_ABC-12345678", sanitized)
        self.assertIn("sk-[REDACTED]", sanitized)

    def test_sanitize_arg_masks_values_inside_set_types(self):
        from app.services.observability import _sanitize_arg

        sanitized = _sanitize_arg({"OPENAI_API_KEY=sk-secret-12345678", "15551234567"})

        self.assertTrue(any("[REDACTED]" in str(item) for item in sanitized))
        self.assertFalse(any("sk-secret-12345678" in str(item) for item in sanitized))

    def test_set_correlation_id_caps_length(self):
        from app.services.observability import set_correlation_id

        value = set_correlation_id("a" * 300)

        self.assertEqual(len(value), 128)


class Story13LoggingConfigurationTests(unittest.TestCase):
    def test_configure_logging_does_not_duplicate_root_filter(self):
        import logging

        from app.config import configure_logging
        from app.services.observability import SafeObservabilityFilter

        configure_logging()
        configure_logging()

        root_logger = logging.getLogger()
        filter_count = sum(isinstance(item, SafeObservabilityFilter) for item in root_logger.filters)
        self.assertEqual(filter_count, 1)


class Story13ObservabilityEndpointTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        from app import create_app

        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def test_health_endpoint_returns_contract(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("status", payload)
        self.assertIn("uptime_seconds", payload)
        self.assertIn("last_error", payload)
        self.assertIn(payload["status"], {"running", "degraded"})

    def test_health_endpoint_includes_request_trace_and_lightweight_metrics(self):
        response = self.client.get("/health", headers={"X-Request-ID": "trace-health-001"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload.get("request_id"), "trace-health-001")
        self.assertEqual(response.headers.get("X-Request-ID"), "trace-health-001")
        self.assertIn("metrics", payload)
        self.assertIn("requests_total", payload["metrics"])
        self.assertIn("responses_4xx_total", payload["metrics"])
        self.assertIn("responses_5xx_total", payload["metrics"])
        self.assertIn("webhook_requests_total", payload["metrics"])
        self.assertIn("webhook_internal_errors_total", payload["metrics"])

    def test_metrics_endpoint_returns_required_baseline_keys(self):
        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("counters", payload)
        self.assertIn("durations", payload)

        counters = payload["counters"]
        self.assertIn("webhook.requests_total", counters)
        self.assertIn("webhook.duplicates_total", counters)
        self.assertIn("webhook.internal_errors_total", counters)
        self.assertIn("webhook.blocked_config_invalid_total", counters)
        self.assertIn("webhook.status_updates_total", counters)
        self.assertIn("webhook.invalid_events_total", counters)
        self.assertIn("webhook.json_decode_errors_total", counters)
        self.assertIn("http.requests_total", counters)
        self.assertIn("http.responses_total", counters)
        self.assertIn("http.responses_4xx_total", counters)
        self.assertIn("http.responses_5xx_total", counters)

        durations = payload["durations"]
        self.assertIn("webhook.handle_message_seconds", durations["totals"])
        self.assertIn("webhook.handle_message_seconds", durations["counts"])
        self.assertIn("http.request_duration_seconds", durations["totals"])
        self.assertIn("http.request_duration_seconds", durations["counts"])

    def test_metrics_endpoint_tracks_http_lifecycle_counts(self):
        self.client.get("/health")
        self.client.get("/webhook")
        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        counters = response.get_json()["counters"]
        self.assertGreaterEqual(counters["http.requests_total"], 3)
        self.assertGreaterEqual(counters["http.responses_total"], 2)
        self.assertGreaterEqual(counters["http.responses_4xx_total"], 1)

    def test_health_and_metrics_are_available_with_incomplete_setup(self):
        with patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta"}, clear=True), patch(
            "app.config.load_dotenv", return_value=None
        ):
            from app import create_app

            app = create_app()
            client = app.test_client()

            health_response = client.get("/health")
            metrics_response = client.get("/metrics")

        self.assertEqual(health_response.status_code, 200)
        health_payload = health_response.get_json()
        self.assertIn("status", health_payload)
        self.assertIn("uptime_seconds", health_payload)
        self.assertIn("last_error", health_payload)

        self.assertEqual(metrics_response.status_code, 200)
        metrics_payload = metrics_response.get_json()
        self.assertIn("counters", metrics_payload)
        self.assertIn("durations", metrics_payload)
        self.assertIn("webhook.requests_total", metrics_payload["counters"])
        self.assertIn(
            "webhook.handle_message_seconds",
            metrics_payload["durations"]["totals"],
        )


class Story13AdvancedObservabilityTests(unittest.TestCase):
    """Tests for inflight gauge, sliding-window error rate, per-endpoint counters,
    and Prometheus text export."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()
        from app import create_app
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    # ------------------------------------------------------------------
    # Snapshot structure
    # ------------------------------------------------------------------

    def test_metrics_snapshot_includes_inflight_key(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("inflight", payload)
        self.assertIsInstance(payload["inflight"], int)

    def test_metrics_snapshot_includes_error_window_key(self):
        response = self.client.get("/metrics")
        payload = response.get_json()
        self.assertIn("errors_last_300s", payload)
        self.assertIsInstance(payload["errors_last_300s"], int)

    def test_metrics_snapshot_includes_endpoints_key(self):
        response = self.client.get("/metrics")
        payload = response.get_json()
        self.assertIn("endpoints", payload)
        self.assertIsInstance(payload["endpoints"], dict)

    # ------------------------------------------------------------------
    # Inflight gauge
    # ------------------------------------------------------------------

    def test_inflight_gauge_is_non_negative(self):
        """The inflight gauge captures the live count at snapshot time.
        The /metrics request itself is in-flight when the snapshot is taken
        (teardown_request decrements *after* the view returns), so the gauge
        reads >= 1. It must never be negative."""
        response = self.client.get("/metrics")
        payload = response.get_json()
        self.assertGreaterEqual(payload["inflight"], 0)

    # ------------------------------------------------------------------
    # Sliding-window error rate
    # ------------------------------------------------------------------

    def test_error_window_records_4xx_response(self):
        """A 403 from the unauthenticated GET /webhook must show up in errors_last_300s."""
        self.client.get("/webhook")  # returns 403
        response = self.client.get("/metrics")
        payload = response.get_json()
        self.assertGreaterEqual(payload["errors_last_300s"], 1)

    # ------------------------------------------------------------------
    # Per-endpoint counters
    # ------------------------------------------------------------------

    def test_per_endpoint_counter_recorded_after_request(self):
        """After hitting /health the endpoint counter must be >= 1."""
        self.client.get("/health")
        response = self.client.get("/metrics")
        endpoints = response.get_json()["endpoints"]
        # At least one endpoint key must exist and have requests_total > 0
        self.assertTrue(
            any(v["requests_total"] >= 1 for v in endpoints.values()),
            f"No endpoint had requests_total >= 1: {endpoints}",
        )

    def test_per_endpoint_error_counter_incremented_on_4xx(self):
        """GET /webhook (403) must increment errors_total for that endpoint."""
        self.client.get("/webhook")  # 403
        response = self.client.get("/metrics")
        endpoints = response.get_json()["endpoints"]
        # Find the endpoint that served the 403
        error_total = sum(v["errors_total"] for v in endpoints.values())
        self.assertGreaterEqual(error_total, 1)

    # ------------------------------------------------------------------
    # Prometheus text export
    # ------------------------------------------------------------------

    def test_prometheus_endpoint_returns_200(self):
        response = self.client.get("/metrics/prometheus")
        self.assertEqual(response.status_code, 200)

    def test_prometheus_endpoint_content_type_is_text_plain(self):
        response = self.client.get("/metrics/prometheus")
        self.assertIn("text/plain", response.content_type)

    def test_prometheus_endpoint_contains_type_lines(self):
        response = self.client.get("/metrics/prometheus")
        body = response.data.decode()
        self.assertIn("# TYPE", body)

    def test_prometheus_endpoint_contains_counter_metrics(self):
        response = self.client.get("/metrics/prometheus")
        body = response.data.decode()
        self.assertIn("http_requests_total", body)
        self.assertIn("webhook_requests_total", body)

    def test_prometheus_endpoint_contains_gauge_metrics(self):
        response = self.client.get("/metrics/prometheus")
        body = response.data.decode()
        self.assertIn("http_inflight_requests", body)
        self.assertIn("http_errors_last_300s", body)

    def test_api_prometheus_endpoint_returns_200(self):
        response = self.client.get("/api/metrics/prometheus")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.content_type)


class Story13SignatureErrorCorrelationTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        from app import create_app

        self.app = create_app()
        self.app.config["APP_SECRET"] = "test-secret"
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def _signature(self, payload: str) -> str:
        digest = hmac.new(
            b"test-secret", msg=payload.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"

    def test_signature_rejection_contains_reason_and_correlation_id(self):
        response = self.client.post("/webhook", data="{}")

        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertEqual(payload.get("reason"), "missing_or_malformed_signature")
        self.assertTrue(payload.get("correlation_id"))
        self.assertEqual(response.headers.get("X-Request-ID"), payload.get("correlation_id"))

    def test_valid_signed_webhook_post_includes_x_request_id_header(self):
        payload = json.dumps(
            {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "contacts": [
                                        {
                                            "wa_id": "15551234567",
                                            "profile": {"name": "Signed Tester"},
                                        }
                                    ],
                                    "messages": [
                                        {"id": "wamid-signed-1", "text": {"body": "hello"}}
                                    ],
                                }
                            }
                        ]
                    }
                ],
            }
        )

        with patch(
            "app.views.process_whatsapp_message",
            return_value={
                "from": "15551234567",
                "message_id": "wamid-signed-1",
                "agent": "Ops",
                "input_text": "hello",
                "reply_text": "reply",
                "status": "sent",
                "error": None,
            },
        ):
            response = self.client.post(
                "/webhook",
                data=payload,
                content_type="application/json",
                headers={"X-Hub-Signature-256": self._signature(payload)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))


if __name__ == "__main__":
    unittest.main()
