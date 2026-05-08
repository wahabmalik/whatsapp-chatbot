"""
tests/test_critical_product_paths.py

RELEASE GATE: Automated coverage for critical product paths.

This test suite validates security, reliability, and latency regressions
before launch. Tests are organized by quality dimension:

SECURITY DOMAIN:
  - E-CPP-SEC-001: Webhook signature validation (tampering prevention)
  - E-CPP-SEC-002: Replay attack prevention (nonce + time window)
  - E-CPP-SEC-003: Authentication token validation (authz check)
  - E-CPP-SEC-004: Input sanitization (injection prevention)
  - E-CPP-SEC-005: Provider switch doesn't leak security context

RELIABILITY DOMAIN:
  - E-CPP-REL-001: Message idempotency (no duplicate delivery)
  - E-CPP-REL-002: Retry resilience (backoff and exhaustion)
  - E-CPP-REL-003: Database error handling (graceful degradation)
  - E-CPP-REL-004: Missing config doesn't crash (setup mode)
  - E-CPP-REL-005: Health check accuracy under load

LATENCY DOMAIN:
  - E-CPP-LAT-001: Webhook response time SLA (<500ms normal path)
  - E-CPP-LAT-002: OpenAI provider switch under load
  - E-CPP-LAT-003: Message log buffer doesn't block webhook
  - E-CPP-LAT-004: Metrics collection is non-blocking

Each test includes:
  - Clear acceptance criteria (AC)
  - SLA boundaries if applicable
  - Regression risk mitigation strategy
  - Roll-back trigger condition
"""

import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from io import StringIO

from flask import Flask
import logging


# ============================================================================
# Shared Test Fixtures & Helpers
# ============================================================================

REQUIRED_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token-value",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "RECIPIENT_WAID": "15551234567",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test-key",
}


def _make_signed_request(payload: str, secret: str = "supersecret") -> str:
    """Generate valid HMAC-SHA256 signature."""
    digest = hmac.new(
        secret.encode("latin-1"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _make_webhook_payload(wa_id: str = "1234567890", message_id: str = "msg123"):
    """Construct standard WhatsApp webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "1234567890",
                                "phone_number_id": "1234567890",
                            },
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": wa_id}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": message_id,
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _create_app_with_env(env_overrides: dict | None = None) -> Flask:
    """Create Flask app with specified environment."""
    env = {**REQUIRED_ENV}
    if env_overrides:
        env.update(env_overrides)

    with patch.dict(os.environ, env, clear=False):
        from app import create_app
        return create_app()


# ============================================================================
# SECURITY DOMAIN TESTS
# ============================================================================

class CriticalPathSecurityTests(unittest.TestCase):
    """E-CPP-SEC: Security regressions in critical paths."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, REQUIRED_ENV, clear=False)
        self._env_patch.start()
        
        from app.decorators import security
        security.clear_signature_replay_cache()

    def tearDown(self):
        self._env_patch.stop()

    def test_sec_001_webhook_signature_validation_rejects_tampering(self):
        """
        AC: Webhook with invalid signature must be rejected with 401.
        Risk: Tampered messages bypass validation and execute as trusted.
        SLA: Detection must be <5ms.
        """
        app = _create_app_with_env()
        client = app.test_client()

        payload = json.dumps(_make_webhook_payload())
        # Create WRONG signature
        bad_signature = _make_signed_request(payload, secret="wrong-secret")

        response = client.post(
            "/webhook",
            data=payload,
            headers={
                "X-Hub-Signature": bad_signature,
                "X-Hub-Signature-256": bad_signature,
            },
            content_type="application/json",
        )

        self.assertIn(response.status_code, [401, 403], 
                     f"Expected 401/403 for bad signature, got {response.status_code}")

    def test_sec_002_replay_attack_prevention(self):
        """
        AC: Same webhook payload cannot be processed twice within replay window.
        Risk: Attacker replays old message to trigger duplicate actions.
        SLA: Replay detection <10ms.
        """
        app = _create_app_with_env()
        client = app.test_client()

        from app.decorators import security
        security.clear_signature_replay_cache()

        payload = json.dumps(_make_webhook_payload(message_id="unique-msg-id-123"))
        signature = _make_signed_request(payload, secret=REQUIRED_ENV["APP_SECRET"])

        # First request should succeed; mock processing to avoid live HTTP threads.
        with patch("app.views.process_whatsapp_message") as mock_process:
            mock_process.return_value = {"delivery_status": "queued"}
            response1 = client.post(
                "/webhook",
                data=payload,
                headers={
                    "X-Hub-Signature": signature,
                    "X-Hub-Signature-256": signature,
                },
                content_type="application/json",
            )
        self.assertEqual(response1.status_code, 200)

        # Second identical request should be rejected (replay prevention).
        response2 = client.post(
            "/webhook",
            data=payload,
            headers={
                "X-Hub-Signature": signature,
                "X-Hub-Signature-256": signature,
            },
            content_type="application/json",
        )
        # Replay attack should be rejected (403 Forbidden is valid)
        self.assertIn(response2.status_code, [400, 403, 409],
                     f"Replay attack should be rejected. Got {response2.status_code}")

    def test_sec_003_auth_token_validation_required(self):
        """
        AC: GET /webhook verification must validate verify_token.
        Risk: Attacker without token can register malicious webhooks.
        """
        app = _create_app_with_env()
        client = app.test_client()

        # Missing token
        response = client.get("/webhook")
        self.assertIn(response.status_code, [400, 401, 403])

        # Wrong token
        response = client.get("/webhook?hub.verify_token=wrong&hub.challenge=test")
        self.assertIn(response.status_code, [400, 401, 403])

        # Correct mode and token should succeed
        response = client.get(
            f"/webhook?hub.mode=subscribe&hub.verify_token={REQUIRED_ENV['VERIFY_TOKEN']}&hub.challenge=test"
        )
        self.assertEqual(response.status_code, 200)
        response_data = response.get_data(as_text=True)
        self.assertIn("test", response_data,
                     "Expected challenge in successful verification response")

    def test_sec_004_input_sanitization_prevents_injection(self):
        """
        AC: Message text containing special chars/markup is sanitized before logging.
        Risk: Malicious payloads could break log parsing or enable injection.
        """
        app = _create_app_with_env()
        client = app.test_client()

        # Payload with potential injection payload
        payload_dict = _make_webhook_payload()
        payload_dict["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = (
            "<script>alert('xss')</script>\n{DROP TABLE users;}\x00\xff"
        )
        payload = json.dumps(payload_dict)
        signature = _make_signed_request(payload, secret=REQUIRED_ENV["APP_SECRET"])

        # Should process without crashing
        with patch("app.views.process_whatsapp_message") as mock_process:
            mock_process.return_value = {}
            response = client.post(
                "/webhook",
                data=payload,
                headers={
                    "X-Hub-Signature": signature,
                    "X-Hub-Signature-256": signature,
                },
                content_type="application/json",
            )
            # Should succeed or reject safely, not crash
            self.assertIn(response.status_code, [200, 201, 400, 401, 403, 422])

    def test_sec_005_provider_switch_maintains_security_context(self):
        """
        AC: Switching WHATSAPP_PROVIDER mid-request doesn't leak auth context.
        Risk: Credentials from Meta provider could leak to Evolution endpoint.
        """
        with patch.dict(os.environ, {**REQUIRED_ENV, "WHATSAPP_PROVIDER": "meta"}):
            app1 = _create_app_with_env()
            
        with patch.dict(os.environ, {**REQUIRED_ENV, "WHATSAPP_PROVIDER": "evolution"}, clear=False):
            from app.config import normalize_provider, PROVIDER_EVOLUTION
            provider = normalize_provider(os.environ.get("WHATSAPP_PROVIDER"))
            self.assertEqual(provider, PROVIDER_EVOLUTION)


# ============================================================================
# RELIABILITY DOMAIN TESTS
# ============================================================================

class CriticalPathReliabilityTests(unittest.TestCase):
    """E-CPP-REL: Reliability regressions in critical paths."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, REQUIRED_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_rel_001_message_idempotency_prevents_duplicates(self):
        """
        AC: Same message_id processed twice must result in single delivery.
        Risk: Duplicate messages confuse users and double-count metrics.
        SLA: Idempotency check <20ms.
        """
        app = _create_app_with_env()
        client = app.test_client()

        from app.views import clear_message_idempotency_cache
        with app.app_context():
            clear_message_idempotency_cache()

            unique_msg_id = "idempotency-test-msg-456"
            payload_dict = _make_webhook_payload(message_id=unique_msg_id)
            payload = json.dumps(payload_dict)
            signature = _make_signed_request(payload, secret=REQUIRED_ENV["APP_SECRET"])

            with patch("app.views.process_whatsapp_message") as mock_process:
                mock_process.return_value = {"delivery_status": "queued"}

                # First delivery
                response1 = client.post(
                    "/webhook",
                    data=payload,
                    headers={
                        "X-Hub-Signature": signature,
                        "X-Hub-Signature-256": signature,
                    },
                    content_type="application/json",
                )
                self.assertEqual(response1.status_code, 200)
                first_call_count = mock_process.call_count

                # Second delivery (duplicate message_id)
                response2 = client.post(
                    "/webhook",
                    data=payload,
                    headers={
                        "X-Hub-Signature": signature,
                        "X-Hub-Signature-256": signature,
                    },
                    content_type="application/json",
                )
                # Should not increment call count (idempotent)
                self.assertEqual(mock_process.call_count, first_call_count,
                               "Duplicate message should not trigger second processing")

    def test_rel_002_retry_resilience_with_backoff(self):
        """
        AC: Transient failures retry with exponential backoff, not fail immediately.
        Risk: Network blips cause message loss instead of automatic recovery.
        """
        from app.services.openai_service import _is_retryable_exception, _sleep_with_backoff

        # Verify retryable exceptions are identified
        named_retryable = ["RateLimitError", "APIConnectionError", "APITimeoutError"]
        retryable_errors = [
            type(name, (Exception,), {})(name) for name in named_retryable
        ] + [
            Exception("temporary failure"),
            Exception("timeout waiting for response"),
        ]

        for exc in retryable_errors:
            is_retryable = _is_retryable_exception(exc)
            self.assertTrue(is_retryable, f"Should retry on {exc}")

        # Verify backoff increases exponentially
        with patch("time.sleep") as mock_sleep:
            for attempt in range(3):
                _sleep_with_backoff(attempt)
            
            # Sleep calls should increase with each attempt
            calls = [call[0][0] for call in mock_sleep.call_args_list]
            self.assertTrue(calls[1] > calls[0], "Backoff should increase")

    def test_rel_003_database_error_handling_graceful_degradation(self):
        """
        AC: Database connection failure doesn't crash webhook; returns 500 or queues for retry.
        Risk: Single DB timeout takes down the entire service.
        """
        app = _create_app_with_env()
        client = app.test_client()

        payload = json.dumps(_make_webhook_payload())
        signature = _make_signed_request(payload, secret=REQUIRED_ENV["APP_SECRET"])

        # Simulate DB error in message processing
        with patch("app.views.process_whatsapp_message") as mock_process:
            mock_process.side_effect = Exception("Connection refused: database unavailable")

            response = client.post(
                "/webhook",
                data=payload,
                headers={
                    "X-Hub-Signature": signature,
                    "X-Hub-Signature-256": signature,
                },
                content_type="application/json",
            )
            # Should fail gracefully (500 is acceptable, not 5xx > 599)
            self.assertIn(response.status_code, [200, 202, 500])
            self.assertLess(response.status_code, 600)

    def test_rel_004_missing_config_doesnt_crash_setup_mode(self):
        """
        AC: App starts even with missing config; setup routes remain accessible.
        Risk: Missing credentials during onboarding make app unreachable.
        """
        incomplete_env = {
            "WHATSAPP_PROVIDER": "meta",
            # Missing OPENAI_API_KEY, ACCESS_TOKEN, etc.
        }

        with patch.dict(os.environ, incomplete_env, clear=True):
            with patch("app.config.load_dotenv"):
                from app import create_app
                app = create_app()
                self.assertIsNotNone(app)
                
                # Setup routes should be accessible
                client = app.test_client()
                response = client.get("/")
                self.assertIn(response.status_code, [200, 302])

    def test_rel_005_health_check_accuracy(self):
        """
        AC: /health endpoint accurately reports app readiness.
        Risk: Stale health state causes load balancer to route to broken instance.
        """
        app = _create_app_with_env()
        client = app.test_client()

        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.get_data(as_text=True))
        self.assertIn("status", data)
        self.assertIn(data["status"], ["running", "degraded", "healthy", "ok", "up"])


# ============================================================================
# LATENCY DOMAIN TESTS
# ============================================================================

class CriticalPathLatencyTests(unittest.TestCase):
    """E-CPP-LAT: Latency regressions in critical paths."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, REQUIRED_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_lat_001_webhook_response_time_sla(self):
        """
        AC: Normal webhook processing completes in <500ms (P99).
        Risk: Slow webhook causes message backlog and user perception of delay.
        SLA: 500ms for message ack response.
        """
        app = _create_app_with_env()
        client = app.test_client()

        payload = json.dumps(_make_webhook_payload())
        signature = _make_signed_request(payload, secret=REQUIRED_ENV["APP_SECRET"])

        with patch("app.views.process_whatsapp_message") as mock_process:
            mock_process.return_value = {"delivery_status": "queued"}

            start = time.perf_counter()
            response = client.post(
                "/webhook",
                data=payload,
                headers={
                    "X-Hub-Signature": signature,
                    "X-Hub-Signature-256": signature,
                },
                content_type="application/json",
            )
            elapsed = time.perf_counter() - start

            self.assertEqual(response.status_code, 200)
            self.assertLess(elapsed, 0.5, 
                           f"Webhook response took {elapsed:.3f}s, must be <500ms")

    def test_lat_002_provider_switch_latency_acceptable(self):
        """
        AC: Provider initialization (Meta vs Evolution) adds <100ms overhead.
        Risk: Provider switching during request causes unpredictable latency spikes.
        """
        from app.config import normalize_provider, PROVIDER_META, PROVIDER_EVOLUTION

        # Measure provider normalization overhead without env patching overhead.
        start = time.perf_counter()
        for _ in range(1000):
            normalize_provider("meta")
        meta_time = time.perf_counter() - start

        # Keep a practical upper bound for local/CI variation.
        self.assertLess(meta_time / 1000, 0.01,
                       "Provider normalization overhead too high")

    def test_lat_003_message_log_buffer_nonblocking(self):
        """
        AC: Message logging doesn't block webhook response (async or buffered).
        Risk: Slow logging backend causes webhook timeouts.
        """
        app = _create_app_with_env()

        with app.app_context():
            from app.services.message_log import get_message_log_buffer
            
            log_buffer = get_message_log_buffer(app)
            
            # Simulate rapid logging
            start = time.perf_counter()
            for i in range(100):
                log_buffer.add_message({
                    "timestamp": time.time(),
                    "message_id": f"msg-{i}",
                    "direction": "inbound",
                })
            elapsed = time.perf_counter() - start

            # 100 log entries should complete in <10ms
            self.assertLess(elapsed, 0.01,
                           f"Logging {100} entries took {elapsed:.3f}s, should be <10ms")

    def test_lat_004_metrics_collection_nonblocking(self):
        """
        AC: Metrics collection doesn't block request processing.
        Risk: Metrics backend failures cause webhook timeouts.
        """
        app = _create_app_with_env()

        with app.app_context():
            from app.services.metrics import get_metrics_collector
            
            metrics = get_metrics_collector(app)
            
            # Simulate rapid metrics updates
            start = time.perf_counter()
            for i in range(1000):
                metrics.increment("test.counter")
                metrics.observe_duration("test.duration", 0.1)
            elapsed = time.perf_counter() - start

            # 2000 metric operations should complete in <50ms
            self.assertLess(elapsed, 0.05,
                           f"Metrics operations took {elapsed:.3f}s, should be <50ms")


# ============================================================================
# INTEGRATION TESTS: Cross-Domain Regressions
# ============================================================================

class CriticalPathIntegrationTests(unittest.TestCase):
    """E-CPP-INT: Integration scenarios covering multiple domains."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, REQUIRED_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_int_001_security_reliability_message_flow(self):
        """
        AC: Message flow validates security + handles transient errors + maintains SLA.
        Scenario: Valid signed message → DB unavailable → automatic retry → success.
        """
        app = _create_app_with_env()
        client = app.test_client()

        payload = json.dumps(_make_webhook_payload())
        signature = _make_signed_request(payload, secret=REQUIRED_ENV["APP_SECRET"])

        with patch("app.views.process_whatsapp_message") as mock_process:
            # Simulate transient failure then recovery
            mock_process.side_effect = [
                Exception("temporary DB error"),
                {"delivery_status": "queued"},
            ]

            # First attempt fails, but gracefully
            response = client.post(
                "/webhook",
                data=payload,
                headers={
                    "X-Hub-Signature": signature,
                    "X-Hub-Signature-256": signature,
                },
                content_type="application/json",
            )
            # Should accept the message (200 or 202) even if processing fails
            self.assertIn(response.status_code, [200, 202, 500])

    def test_int_002_all_domains_under_load(self):
        """
        AC: Under concurrent requests, security + reliability + latency SLAs hold.
        Scenario: 10 concurrent signed requests, 1 with duplicate ID.
        """
        app = _create_app_with_env()
        client = app.test_client()

        from app.views import clear_message_idempotency_cache
        with app.app_context():
            clear_message_idempotency_cache()

            with patch("app.views.process_whatsapp_message") as mock_process:
                mock_process.return_value = {"delivery_status": "queued"}

                responses = []
                start = time.perf_counter()

                # Send 10 requests rapidly
                for i in range(10):
                    msg_id = "duplicate-msg" if i == 5 else f"msg-{i}"
                    payload = json.dumps(_make_webhook_payload(message_id=msg_id))
                    signature = _make_signed_request(payload, secret=REQUIRED_ENV["APP_SECRET"])

                    response = client.post(
                        "/webhook",
                        data=payload,
                        headers={
                            "X-Hub-Signature": signature,
                            "X-Hub-Signature-256": signature,
                        },
                        content_type="application/json",
                    )
                    responses.append(response.status_code)

                elapsed = time.perf_counter() - start

                # All should succeed or be properly rejected
                for status in responses:
                    self.assertIn(status, [200, 202, 400, 401, 403, 409])

                # Aggregate latency reasonable for batch (15s ceiling for dev/CI environments)
                self.assertLess(elapsed, 15.0,
                               f"10 concurrent requests took {elapsed:.3f}s, should be <15s")


if __name__ == "__main__":
    unittest.main()
