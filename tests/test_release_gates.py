"""
tests/test_release_gates.py

Release-gate test suite for Epic 4.1.2.
Tests are grouped by gate domain:
  - ReleaseSecurityGateTests        (E4-SEC-*)
  - ReleaseWebhookVerificationTests (E4-SEC-06/07)
  - ReleaseHealthGateTests          (E4-OPS/health)
  - ReleaseCorrelationIdTests       (FR8 propagation)
  - ReleaseOutboundGateTests        (E4-REL-04 + BLOCKED items for FR5)
  - ReleaseOpenAIContractTests      (FR4 controlled failures)

Skipped tests are marked with the blocking story and the exact behavior
that must be implemented before the skip can be removed.
"""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
import logging
from unittest.mock import Mock, patch

from flask import Flask


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

REQUIRED_ENV = {
    "ACCESS_TOKEN": "token",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "RECIPIENT_WAID": "15551234567",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
}

_PAYLOAD = "{}"


def _valid_signature(payload: str, secret: str = "test-secret") -> str:
    digest = hmac.new(
        secret.encode("latin-1"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _make_security_app(secret: str = "test-secret") -> Flask:
    from app.decorators import security

    security.clear_signature_replay_cache()

    app = Flask(__name__)
    app.config.update(
        {
            "WHATSAPP_PROVIDER": "meta",
            "APP_SECRET": secret,
            "SIGNATURE_MAX_SKEW_SECONDS": 300,
            "SIGNATURE_REPLAY_WINDOW_SECONDS": 300,
        }
    )

    @app.route("/secured", methods=["POST"])
    @security.signature_required
    def _secured():
        from flask import jsonify

        return jsonify({"status": "ok"}), 200

    return app


# ---------------------------------------------------------------------------
# E4-SEC-05: positive acceptance path (missing from existing suite)
# ---------------------------------------------------------------------------

class ReleaseSecurityGateTests(unittest.TestCase):
    """Gate E4-SEC — signature decorator critical paths."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta"}, clear=False)
        self._env_patch.start()

        from app.decorators import security
        security.clear_signature_replay_cache()
        self.app = _make_security_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    # E4-SEC-05 — valid request MUST be accepted (positive path)
    def test_valid_signature_request_accepted(self):
        payload = '{"event":"message"}'
        sig = _valid_signature(payload, "test-secret")
        ts = "1700000000"

        with patch("app.decorators.security.time.time", return_value=1700000010):
            response = self.client.post(
                "/secured",
                data=payload,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-Hub-Signature-Timestamp": ts,
                    "Content-Type": "application/json",
                },
            )

        self.assertEqual(response.status_code, 200)

    # E4-SEC-08 — rejection body must not expose APP_SECRET
    def test_rejection_does_not_expose_app_secret(self):
        response = self.client.post(
            "/secured",
            data="{}",
            headers={"X-Hub-Signature-256": "sha256=bad"},
        )
        self.assertEqual(response.status_code, 403)
        body = response.get_data(as_text=True)
        self.assertNotIn("test-secret", body)
        self.assertNotIn("supersecret", body)


# ---------------------------------------------------------------------------
# E4-SEC-06/07: GET webhook verification (positive and mismatch paths)
# ---------------------------------------------------------------------------

class ReleaseWebhookVerificationTests(unittest.TestCase):
    """Gate E4-SEC — GET /webhook challenge verification."""

    def setUp(self):
        self._env_patch = patch.dict(
            os.environ,
            {
                **REQUIRED_ENV,
                "WHATSAPP_PROVIDER": "meta",
            },
            clear=False,
        )
        self._env_patch.start()

        from app.views import webhook_blueprint

        self.app = Flask(__name__)
        self.app.config.update(
            {
                "WHATSAPP_PROVIDER": "meta",
                "VERIFY_TOKEN": "verify-token",
                "ACCESS_TOKEN": "token",
                "APP_SECRET": "supersecret",
                "PHONE_NUMBER_ID": "1234567890",
                "VERSION": "v18.0",
                "RECIPIENT_WAID": "15551234567",
            }
        )
        self.app.register_blueprint(webhook_blueprint)
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    # E4-SEC-06 — valid mode+token returns challenge with 200
    def test_webhook_get_challenge_positive_path(self):
        response = self.client.get(
            "/webhook",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"abc123", response.data)

    # E4-SEC-07 — mismatched verify token returns 403
    def test_webhook_get_challenge_token_mismatch(self):
        response = self.client.get(
            "/webhook",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(response.status_code, 403)

    # E4-SEC-07b — missing mode parameter returns 403
    def test_webhook_get_challenge_missing_mode(self):
        response = self.client.get(
            "/webhook",
            query_string={
                "hub.verify_token": "verify-token",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Health endpoint gate
# ---------------------------------------------------------------------------

class ReleaseHealthGateTests(unittest.TestCase):
    """Gate E4-OPS — /health endpoint contract."""

    def _make_app(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            from app.views import webhook_blueprint
            from app.views_dashboard import dashboard_blueprint
            from datetime import datetime, timezone

            app = Flask(
                __name__,
                template_folder="../app/templates",
                static_folder="../app/static",
            )
            app.config.update(
                {
                    "SECRET_KEY": "test",
                    "ACCESS_TOKEN": "token",
                    "APP_SECRET": "supersecret",
                    "PHONE_NUMBER_ID": "1234567890",
                    "VERIFY_TOKEN": "verify-token",
                    "OPENAI_API_KEY": "sk-test",
                    "VERSION": "v18.0",
                    "RECIPIENT_WAID": "15551234567",
                }
            )
            app.register_blueprint(webhook_blueprint)
            app.register_blueprint(dashboard_blueprint)
            app.extensions["app_started_at"] = datetime.now(timezone.utc)
        return app

    def test_health_endpoint_returns_status_and_uptime(self):
        app = self._make_app()
        client = app.test_client()
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("status", payload)
        self.assertIn("uptime_seconds", payload)
        self.assertIn(payload["status"], {"running", "degraded"})

    def test_health_endpoint_accessible_without_operator_session(self):
        """Health must be readable by monitoring tools, not just operators."""
        app = self._make_app()
        client = app.test_client()
        response = client.get("/api/health", follow_redirects=False)
        # Must not redirect to operator access — health is public
        self.assertNotEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# FR8 correlation ID propagation
# ---------------------------------------------------------------------------

class ReleaseCorrelationIdTests(unittest.TestCase):
    """Gate E4-SEC/REL — X-Request-ID propagation through webhook handler."""

    def setUp(self):
        from app.views import webhook_blueprint

        self.app = Flask(__name__)
        self.app.config.update(
            {
                "VERIFY_TOKEN": "verify-token",
                "ACCESS_TOKEN": "token",
                "APP_SECRET": "test-secret",
                "PHONE_NUMBER_ID": "1234567890",
                "VERSION": "v18.0",
                "RECIPIENT_WAID": "15551234567",
                "IDEMPOTENCY_WINDOW_SECONDS": 300,
                "SIGNATURE_MAX_SKEW_SECONDS": 300,
                "SIGNATURE_REPLAY_WINDOW_SECONDS": 300,
            }
        )
        self.app.register_blueprint(webhook_blueprint)
        self.client = self.app.test_client()

    def _signed_post(self, payload: dict, request_id: str = "corr-001") -> tuple:
        import json
        from app.decorators.security import clear_signature_replay_cache

        clear_signature_replay_cache()
        body = json.dumps(payload)
        sig = _valid_signature(body, "test-secret")
        headers = {
            "X-Hub-Signature-256": sig,
            "X-Hub-Signature-Timestamp": "1700000000",
            "X-Request-ID": request_id,
            "Content-Type": "application/json",
        }
        with patch("app.decorators.security.time.time", return_value=1700000010):
            resp = self.client.post("/webhook", data=body, headers=headers)
        return resp

    def test_correlation_id_propagated_through_valid_message(self):
        """The handler must consume X-Request-ID without error."""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [
                                    {"wa_id": "15551234567", "profile": {"name": "Tester"}}
                                ],
                                "messages": [{"id": "wamid-corr-1", "text": {"body": "hi"}}],
                            }
                        }
                    ]
                }
            ],
        }
        with patch("app.views.process_whatsapp_message") as mock_proc:
            mock_proc.return_value = {
                "from": "15551234567",
                "name": "Tester",
                "agent": "bot",
                "input_text": "hi",
                "reply_text": "hello",
                "status": "sent",
            }
            resp = self._signed_post(payload, request_id="corr-test-001")

        self.assertEqual(resp.status_code, 200)
        # Verify request_id was forwarded to the processing function
        _, kwargs = mock_proc.call_args
        self.assertEqual(kwargs.get("request_id"), "corr-test-001")

    def test_rejection_log_includes_request_id(self):
        """Signature rejection must emit log containing the correlation ID."""
        with self.assertLogs("root", level=logging.INFO) as cm:
            self.client.post(
                "/webhook",
                data="{}",
                headers={
                    "X-Hub-Signature-256": "sha256=bad",
                    "X-Request-ID": "corr-rej-001",
                    "Content-Type": "application/json",
                },
            )
        combined = "\n".join(cm.output)
        self.assertIn("corr-rej-001", combined)


# ---------------------------------------------------------------------------
# FR5 outbound delivery gate (E4-REL-04/05/06)
# ---------------------------------------------------------------------------

class ReleaseOutboundGateTests(unittest.TestCase):
    """Gate E4-REL — send_message error contract and retry/fallback behavior."""

    def _app_ctx(self):
        app = Flask(__name__)
        app.config.update(
            {
                "WHATSAPP_PROVIDER": "meta",
                "ACCESS_TOKEN": "token",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "ESCALATION_CONFIDENCE_THRESHOLD": 0.35,
                "ESCALATION_KEYWORDS": ["human", "agent", "escalate"],
                "WHATSAPP_DEFER_RETRIES": False,
            }
        )
        return app

    def _inbound_body(self, wa_id: str = "15551234567"):
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [
                                    {
                                        "wa_id": wa_id,
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                                "messages": [{"id": "wamid-test-1", "text": {"body": "hello"}}],
                            }
                        }
                    ]
                }
            ]
        }

    def test_keyword_escalation_emits_reason_and_masked_queue_record(self):
        from app.utils.whatsapp_utils import process_whatsapp_message

        app = self._app_ctx()
        with tempfile.TemporaryDirectory() as tmp_dir:
            queue_path = os.path.join(tmp_dir, "operator_review_queue.jsonl")
            app.config["ESCALATION_QUEUE_PATH"] = queue_path

            body = self._inbound_body("19998887777")
            body["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "I need a human now"

            with app.app_context():
                with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}):
                    with patch(
                        "app.utils.whatsapp_utils.send_message",
                        return_value={"status": "sent", "error": None, "operator_review_flagged": False},
                    ):
                        delivery = process_whatsapp_message(body, request_id="corr-keyword")

            self.assertTrue(delivery.get("operator_review_flagged"))
            self.assertEqual(delivery.get("operator_review_reason"), "escalation_keyword")
            self.assertTrue(delivery.get("review_artifact_queued"))

            with open(queue_path, "r", encoding="utf-8") as artifact_file:
                lines = artifact_file.readlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record.get("reason"), "escalation_keyword")
            self.assertEqual(record.get("correlation_id"), "corr-keyword")
            self.assertEqual(record.get("message_id"), "wamid-test-1")
            self.assertEqual(record.get("masked_user_handle"), "199...7777")
            self.assertNotIn("19998887777", lines[0])

    def test_low_confidence_escalation_sets_deterministic_reason(self):
        from app.utils.whatsapp_utils import process_whatsapp_message

        app = self._app_ctx()
        app.config["ESCALATION_CONFIDENCE_THRESHOLD"] = 0.80

        with tempfile.TemporaryDirectory() as tmp_dir:
            app.config["ESCALATION_QUEUE_PATH"] = os.path.join(tmp_dir, "operator_review_queue.jsonl")
            with app.app_context():
                with patch("app.utils.whatsapp_utils.find_faq_answer", return_value=None), patch(
                    "app.utils.whatsapp_utils._generate_reply_result",
                    return_value={
                        "ok": True,
                        "status": "success",
                        "reply_text": "AI says hi",
                        "confidence": 0.25,
                        "metadata": {},
                        "error_code": None,
                        "error_detail": None,
                    },
                ), patch(
                    "app.utils.whatsapp_utils.send_message",
                    return_value={"status": "sent", "error": None, "operator_review_flagged": False},
                ):
                    delivery = process_whatsapp_message(self._inbound_body(), request_id="corr-low-confidence")

        self.assertTrue(delivery.get("operator_review_flagged"))
        self.assertEqual(delivery.get("operator_review_reason"), "low_confidence")

    def test_fallback_escalation_reason_is_outbound_failure(self):
        from app.utils.whatsapp_utils import process_whatsapp_message

        app = self._app_ctx()
        with tempfile.TemporaryDirectory() as tmp_dir:
            app.config["ESCALATION_QUEUE_PATH"] = os.path.join(tmp_dir, "operator_review_queue.jsonl")
            with app.app_context():
                with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}), patch(
                    "app.utils.whatsapp_utils.send_message",
                    return_value={
                        "status": "fallback_sent",
                        "error": "Failed to send message",
                        "operator_review_flagged": True,
                        "operator_review_reason": "outbound_fallback_failure",
                    },
                ):
                    delivery = process_whatsapp_message(self._inbound_body(), request_id="corr-fallback")

        self.assertTrue(delivery.get("operator_review_flagged"))
        self.assertEqual(delivery.get("operator_review_reason"), "outbound_fallback_failure")

    # E4-REL-04 — structured error returned on timeout (current contract)
    def test_send_message_timeout_returns_structured_error(self):
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post") as mock_post:
                mock_post.side_effect = req_lib.Timeout()
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)

    # E4-REL-04b — structured error returned on generic RequestException
    def test_send_message_request_exception_returns_structured_error(self):
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post") as mock_post:
                mock_post.side_effect = req_lib.ConnectionError("unreachable")
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data)

        self.assertFalse(result["ok"])

    # E4-REL-04c — successful send returns ok=True with response_status
    def test_send_message_success_returns_ok_true(self):
        from unittest.mock import MagicMock
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"messages":[{"id":"wamid-1"}]}'

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", return_value=mock_resp):
                result = send_message(data)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")

    def test_outbound_retry_attempts_match_spec(self):
        """
        E4-REL-05: send_message must retry exactly 3 times with 1/2/4 s backoff
        before returning failure.
        """
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        call_times = []

        from unittest.mock import MagicMock

        def failing_then_fallback_post(*args, **kwargs):
            call_times.append(True)
            # 4 primary attempts fail, fallback send succeeds.
            if len(call_times) <= 4:
                raise req_lib.Timeout()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"content-type": "application/json"}
            mock_resp.text = "{}"
            mock_resp.raise_for_status = lambda: None
            return mock_resp

        with app.app_context():
            with patch(
                "app.utils.whatsapp_utils.requests.post",
                side_effect=failing_then_fallback_post,
            ):
                with patch("app.utils.whatsapp_utils.time.sleep") as mock_sleep:
                    result = send_message(data)
                    sleep_args = [c.args[0] for c in mock_sleep.call_args_list]

        # 1 initial + 3 retries + 1 fallback send
        self.assertEqual(len(call_times), 5)
        self.assertAlmostEqual(sleep_args[0], 1, delta=0.1)
        self.assertAlmostEqual(sleep_args[1], 2, delta=0.1)
        self.assertAlmostEqual(sleep_args[2], 4, delta=0.1)
        self.assertTrue(result.get("fallback_sent"))

    def test_fallback_sent_after_retry_exhaustion(self):
        """
        E4-REL-06: After 3 failed retries, a deterministic fallback must be sent
        and an operator-review flag must be emitted to logs/queue.
        """
        from unittest.mock import MagicMock
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        attempts = {"count": 0}

        def flaky_post(*args, **kwargs):
            attempts["count"] += 1
            # Exhaust all primary attempts, then succeed on fallback send.
            if attempts["count"] <= 4:
                raise req_lib.Timeout()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"content-type": "application/json"}
            mock_resp.text = "{}"
            mock_resp.raise_for_status = lambda: None
            return mock_resp

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=flaky_post):
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data)

        # After retry exhaustion, the implementation should indicate fallback was sent.
        self.assertTrue(result.get("fallback_sent"))
        self.assertTrue(result.get("operator_review_flagged"))
        self.assertEqual(result.get("status"), "fallback_sent")

    def test_fallback_retries_continue_after_first_fallback_failure(self):
        """
        Fallback delivery should honor WHATSAPP_FALLBACK_MAX_RETRIES when
        an earlier fallback attempt fails.
        """
        from unittest.mock import MagicMock
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        app.config["WHATSAPP_FALLBACK_MAX_RETRIES"] = 2
        data = get_text_message_input("15551234567", "hello")

        attempts = {"count": 0}

        def post_side_effect(*args, **kwargs):
            attempts["count"] += 1
            # 4 primary attempts fail, 1st fallback fails, 2nd fallback succeeds.
            if attempts["count"] <= 5:
                raise req_lib.Timeout()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"content-type": "application/json"}
            mock_resp.text = "{}"
            mock_resp.raise_for_status = lambda: None
            return mock_resp

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=post_side_effect):
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data)

        self.assertTrue(result.get("fallback_sent"))
        self.assertEqual(result.get("status"), "fallback_sent")
        self.assertEqual(attempts["count"], 6)

    def test_process_whatsapp_message_targets_inbound_sender(self):
        from app.utils.whatsapp_utils import process_whatsapp_message

        app = self._app_ctx()

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}):
                with patch(
                    "app.utils.whatsapp_utils.send_message",
                    return_value={"status": "sent", "error": None},
                ) as mock_send:
                    process_whatsapp_message(self._inbound_body("19998887777"), request_id="req-1")

        sent_payload = json.loads(mock_send.call_args.args[0])
        self.assertEqual(sent_payload["to"], "19998887777")

    def test_send_message_uses_evolution_endpoint_and_apikey_header(self):
        from unittest.mock import MagicMock

        from app.utils.whatsapp_utils import get_text_message_input, send_message

        app = Flask(__name__)
        app.config.update(
            {
                "WHATSAPP_PROVIDER": "evolution",
                "EVOLUTION_API_URL": "https://evolution.example.com",
                "EVOLUTION_API_KEY": "evo-key",
                "EVOLUTION_INSTANCE_NAME": "bot-instance",
            }
        )
        data = get_text_message_input("15551234567", "hello")

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"key":{"id":"evo-1"}}'
        mock_resp.raise_for_status = lambda: None

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", return_value=mock_resp) as mock_post:
                result = send_message(data)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(
            mock_post.call_args.kwargs["headers"]["apikey"],
            "evo-key",
        )
        self.assertEqual(
            mock_post.call_args.args[0],
            "https://evolution.example.com/message/sendText/bot-instance",
        )
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["number"],
            "15551234567",
        )

    def test_send_message_uses_configured_timeout(self):
        from unittest.mock import MagicMock

        from app.utils.whatsapp_utils import get_text_message_input, send_message

        app = self._app_ctx()
        app.config["WHATSAPP_SEND_TIMEOUT_SECONDS"] = 3.5
        data = get_text_message_input("15551234567", "hello")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = "{}"
        mock_resp.raise_for_status = lambda: None

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", return_value=mock_resp) as mock_post:
                send_message(data)

        self.assertEqual(mock_post.call_args.kwargs["timeout"], 3.5)

    def test_send_message_defers_remaining_retries_when_enabled(self):
        import requests as req_lib

        from app.utils.whatsapp_utils import get_text_message_input, send_message

        app = self._app_ctx()
        app.config["WHATSAPP_DEFER_RETRIES"] = True
        data = get_text_message_input("15551234567", "hello")
        submitted = []

        class FakeService:
            def submit(self, fn, *args, **kwargs):
                submitted.append((fn, args, kwargs))
                return Mock()

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=req_lib.Timeout()):
                with patch("app.utils.whatsapp_utils.get_background_delivery_service", return_value=FakeService()):
                    with patch("app.utils.whatsapp_utils.time.sleep") as mock_sleep:
                        result = send_message(data, request_id="req-deferred")

        self.assertEqual(result["status"], "retrying")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(len(submitted), 1)
        mock_sleep.assert_not_called()

    def test_deferred_delivery_completion_logs_final_outcome(self):
        from unittest.mock import MagicMock

        from app.services.message_log import get_message_log_buffer
        from app.utils.whatsapp_utils import _complete_deferred_delivery, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = "{}"
        mock_resp.raise_for_status = lambda: None

        with patch("app.utils.whatsapp_utils.requests.post", return_value=mock_resp):
            result = _complete_deferred_delivery(
                app,
                data,
                "req-bg-log",
                {
                    "wa_id": "15551234567",
                    "message_id": "wamid-bg-1",
                    "to_num": "15551234567",
                    "agent": "Ops",
                    "input_text": "hello",
                    "reply_text": "reply",
                },
                0.0,
            )

        entries = get_message_log_buffer(app).get_all()
        self.assertTrue(result["ok"])
        self.assertEqual(entries[0]["correlation_id"], "req-bg-log")
        self.assertEqual(entries[0]["status"], "sent")
        self.assertEqual(entries[0]["message_id"], "wamid-bg-1")
        self.assertFalse(entries[0]["operator_review_flagged"])

    def test_deferred_delivery_fallback_sent_emits_terminal_log_and_operator_artifact(self):
        import requests

        from app.services.message_log import get_message_log_buffer
        from app.utils.whatsapp_utils import _complete_deferred_delivery, get_text_message_input

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._app_ctx()
            app.config["ESCALATION_QUEUE_PATH"] = os.path.join(tmp_dir, "operator_review_queue.jsonl")
            data = get_text_message_input("15551234567", "hello")

            with patch(
                "app.utils.whatsapp_utils._send_request",
                side_effect=[
                    requests.Timeout("attempt-1"),
                    requests.Timeout("attempt-2"),
                    requests.Timeout("attempt-3"),
                    Mock(status_code=200, headers={"content-type": "application/json"}, text="{}", raise_for_status=lambda: None),
                ],
            ), patch("app.utils.whatsapp_utils.time.sleep"):
                result = _complete_deferred_delivery(
                    app,
                    data,
                    "req-bg-fallback",
                    {
                        "wa_id": "15551234567",
                        "message_id": "wamid-bg-fallback-1",
                        "to_num": "15551234567",
                        "agent": "Ops",
                        "input_text": "hello",
                        "reply_text": "reply",
                    },
                    0.0,
                )

            entries = get_message_log_buffer(app).get_all()
            with open(app.config["ESCALATION_QUEUE_PATH"], encoding="utf-8") as fh:
                artifact = json.loads(next(line for line in fh if line.strip()))

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "fallback_sent")
        self.assertTrue(result["review_artifact_queued"])
        self.assertIsNone(result["review_artifact_error"])
        self.assertEqual(entries[0]["correlation_id"], "req-bg-fallback")
        self.assertEqual(entries[0]["message_id"], "wamid-bg-fallback-1")
        self.assertEqual(entries[0]["status"], result["status"])
        self.assertEqual(entries[0]["operator_review_reason"], artifact["reason"])
        self.assertTrue(entries[0]["operator_review_flagged"])
        self.assertTrue(entries[0]["review_artifact_queued"])
        self.assertEqual(artifact["correlation_id"], "req-bg-fallback")
        self.assertEqual(artifact["message_id"], "wamid-bg-fallback-1")

    def test_deferred_delivery_failure_emits_terminal_log_and_operator_artifact(self):
        import requests

        from app.services.message_log import get_message_log_buffer
        from app.utils.whatsapp_utils import _complete_deferred_delivery, get_text_message_input

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._app_ctx()
            app.config["ESCALATION_QUEUE_PATH"] = os.path.join(tmp_dir, "operator_review_queue.jsonl")
            data = get_text_message_input("15551234567", "hello")

            with patch("app.utils.whatsapp_utils._send_request", side_effect=requests.Timeout("always fail")), \
                 patch("app.utils.whatsapp_utils.time.sleep"):
                result = _complete_deferred_delivery(
                    app,
                    data,
                    "req-bg-fail",
                    {
                        "wa_id": "15551234567",
                        "message_id": "wamid-bg-fail-1",
                        "to_num": "15551234567",
                        "agent": "Ops",
                        "input_text": "hello",
                        "reply_text": "reply",
                    },
                    0.0,
                )

            entries = get_message_log_buffer(app).get_all()
            with open(app.config["ESCALATION_QUEUE_PATH"], encoding="utf-8") as fh:
                artifact = json.loads(next(line for line in fh if line.strip()))

        self.assertFalse(result["ok"])
        self.assertTrue(result["review_artifact_queued"])
        self.assertIsNone(result["review_artifact_error"])
        self.assertEqual(entries[0]["correlation_id"], "req-bg-fail")
        self.assertEqual(entries[0]["message_id"], "wamid-bg-fail-1")
        self.assertEqual(entries[0]["status"], result["status"])
        self.assertEqual(entries[0]["operator_review_reason"], artifact["reason"])
        self.assertTrue(entries[0]["operator_review_flagged"])
        self.assertTrue(entries[0]["review_artifact_queued"])
        self.assertEqual(artifact["correlation_id"], "req-bg-fail")
        self.assertEqual(artifact["message_id"], "wamid-bg-fail-1")

    def test_send_message_records_outbound_metrics(self):
        from unittest.mock import MagicMock
        from app.services.metrics import get_metrics_collector
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = "{}"
        mock_resp.raise_for_status = lambda: None

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", return_value=mock_resp):
                send_message(data, request_id="req-metrics")
            snapshot = get_metrics_collector(app).snapshot()

        self.assertGreaterEqual(snapshot["counters"]["whatsapp.send_attempt"], 1)
        self.assertGreaterEqual(snapshot["counters"]["whatsapp.send_success"], 1)
        self.assertGreaterEqual(snapshot["durations"]["counts"]["whatsapp.send_duration"], 1)
        self.assertGreaterEqual(snapshot["durations"]["counts"]["whatsapp.send_attempt_duration"], 1)

    def test_keyword_matching_avoids_simple_substring_false_positive(self):
        from app.utils.whatsapp_utils import _contains_escalation_keyword

        self.assertFalse(_contains_escalation_keyword("management update", ["agent"]))
        self.assertTrue(_contains_escalation_keyword("need agent help", ["agent"]))

    def test_send_message_emits_correlation_id_in_outbound_logs(self):
        """
        AC4: Outbound attempts must include the correlation ID in log entries.
        """
        from unittest.mock import MagicMock
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = "{}"
        mock_resp.raise_for_status = lambda: None

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", return_value=mock_resp):
                with self.assertLogs("root", level=logging.DEBUG) as cm:
                    send_message(data, request_id="corr-outbound-001")

        combined = "\n".join(cm.output)
        self.assertIn("corr-outbound-001", combined)

    def test_send_message_no_duplicate_after_confirmed_success(self):
        """
        AC5: Once a send succeeds, no further attempts or fallback sends occur.
        The send loop must return immediately on the first successful response.
        """
        from unittest.mock import MagicMock
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = "{}"
        mock_resp.raise_for_status = lambda: None

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", return_value=mock_resp) as mock_post:
                result = send_message(data, request_id="corr-dedup-001")

        # Exactly one HTTP call — no retry, no fallback
        self.assertEqual(mock_post.call_count, 1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 1)
        self.assertFalse(result["fallback_sent"])


# ---------------------------------------------------------------------------
# Reliable delivery contract (Story: transient failures must not silently drop
# a conversation)
# ---------------------------------------------------------------------------

class ReleaseOutboundDeliveryContractTests(unittest.TestCase):
    """
    Release gate: replies must be sent reliably even when downstream APIs are
    unstable — transient failures must never silently drop a conversation.

    AC1: A transient failure triggers a retry; the message is delivered.
    AC2: After retry exhaustion a fallback notification is sent, not a drop.
    AC3: A confirmed success stops the send loop immediately (no duplicates).
    AC4: The deferred path schedules a retry; the message is not dropped.
    AC4b: If the background executor is unavailable, delivery falls back to
          synchronous retries — no silent drop.
    """

    def _app_ctx(self, extra=None):
        app = Flask(__name__)
        app.config.update(
            {
                "WHATSAPP_PROVIDER": "meta",
                "ACCESS_TOKEN": "token",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "WHATSAPP_DEFER_RETRIES": False,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            }
        )
        if extra:
            app.config.update(extra)
        return app

    def _ok_response(self):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "application/json"}
        resp.text = '{"messages": [{"id": "wamid-test"}]}'
        resp.raise_for_status = lambda: None
        return resp

    # --- AC1: transient failure triggers retry, not a silent drop ----------

    def test_single_transient_timeout_is_retried_and_delivered(self):
        """AC1: A single transient timeout must be retried; message delivered."""
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")
        ok = self._ok_response()
        call_count = [0]

        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise req_lib.Timeout("transient")
            return ok

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=_side_effect):
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data, request_id="req-rel-ac1-001")

        self.assertTrue(result["ok"], "Message must be delivered after one transient timeout")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(call_count[0], 2, "Exactly 2 HTTP calls: 1 failure + 1 success")
        self.assertFalse(result["fallback_sent"])

    def test_connection_error_is_retried_same_as_timeout(self):
        """AC1b: Connection errors must also trigger retry, not a silent drop."""
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")
        ok = self._ok_response()
        call_count = [0]

        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise req_lib.ConnectionError("connection refused")
            return ok

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=_side_effect):
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data, request_id="req-rel-ac1b-001")

        self.assertTrue(result["ok"], "Connection error must trigger retry, not drop")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(call_count[0], 2)

    # --- AC2: retry exhaustion never silently drops — fallback is sent -----

    def test_retry_exhaustion_sends_fallback_not_silent_drop(self):
        """AC2: After retry exhaustion a fallback must be sent, not a silent drop."""
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")
        ok = self._ok_response()
        call_count = [0]

        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 4:  # all 4 primary attempts fail
                raise req_lib.Timeout("unstable")
            return ok  # fallback attempt succeeds

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=_side_effect):
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data, request_id="req-rel-ac2-001")

        self.assertTrue(result.get("fallback_sent"), "Fallback must be sent — not a silent drop")
        self.assertEqual(result["status"], "fallback_sent")
        self.assertTrue(result["operator_review_flagged"])

    def test_complete_delivery_failure_notifies_operator_not_silent_drop(self):
        """AC2b: Even when fallback also fails, operator is notified — not silently dropped."""
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=req_lib.Timeout("always fails")):
                with patch("app.utils.whatsapp_utils.time.sleep"):
                    result = send_message(data, request_id="req-rel-ac2b-001")

        self.assertFalse(result["ok"])
        self.assertFalse(result.get("fallback_sent"))
        self.assertTrue(result["operator_review_flagged"], "Operator must be notified on total failure")
        self.assertEqual(result.get("operator_review_reason"), "outbound_fallback_failure")

    # --- AC3: no duplicate sends after confirmed success -------------------

    def test_confirmed_success_stops_send_loop_immediately(self):
        """AC3: Once a send is confirmed successful, no further retries or fallback."""
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx()
        data = get_text_message_input("15551234567", "hello")

        with app.app_context():
            with patch(
                "app.utils.whatsapp_utils.requests.post", return_value=self._ok_response()
            ) as mock_post:
                result = send_message(data, request_id="req-rel-ac3-001")

        self.assertEqual(mock_post.call_count, 1, "Exactly one HTTP call — no duplicates")
        self.assertTrue(result["ok"])
        self.assertFalse(result["fallback_sent"])
        self.assertEqual(result["attempts"], 1)

    # --- AC4: deferred path schedules retry, does not drop message ---------

    def test_deferred_retry_path_schedules_retry_on_initial_failure(self):
        """AC4: DEFER_RETRIES=True + initial failure → deferred=True, retry enqueued."""
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx({"WHATSAPP_DEFER_RETRIES": True})
        data = get_text_message_input("15551234567", "hello")
        submitted = []

        class FakeDeliveryService:
            def submit(self, fn, *args, **kwargs):
                submitted.append(fn)
                return Mock()

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=req_lib.Timeout()):
                with patch(
                    "app.utils.whatsapp_utils.get_background_delivery_service",
                    return_value=FakeDeliveryService(),
                ):
                    result = send_message(data, request_id="req-rel-ac4-001")

        self.assertTrue(result.get("deferred"), "deferred=True means message is not dropped")
        self.assertEqual(result["status"], "retrying")
        self.assertEqual(len(submitted), 1, "Retry task must be enqueued")

    def test_deferred_executor_failure_falls_back_to_synchronous_retry(self):
        """AC4b: If executor is unavailable, synchronous retry runs — no silent drop."""
        import requests as req_lib
        from app.utils.whatsapp_utils import send_message, get_text_message_input

        app = self._app_ctx({"WHATSAPP_DEFER_RETRIES": True})
        data = get_text_message_input("15551234567", "hello")
        ok = self._ok_response()
        call_count = [0]

        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise req_lib.Timeout("initial failure")
            return ok

        class BrokenExecutor:
            def submit(self, fn, *args, **kwargs):
                raise RuntimeError("executor unavailable")

        with app.app_context():
            with patch("app.utils.whatsapp_utils.requests.post", side_effect=_side_effect):
                with patch(
                    "app.utils.whatsapp_utils.get_background_delivery_service",
                    return_value=BrokenExecutor(),
                ):
                    with patch("app.utils.whatsapp_utils.time.sleep"):
                        result = send_message(data, request_id="req-rel-ac4b-001")

        self.assertTrue(result["ok"], "Synchronous fallback must deliver when executor unavailable")
        self.assertFalse(result.get("deferred", False), "deferred must not be set on sync path")


# ---------------------------------------------------------------------------
# FR4: OpenAI controlled failure state contract
# ---------------------------------------------------------------------------

class ReleaseOpenAIContractTests(unittest.TestCase):
    """Gate E4-REL — OpenAI failure classification tests."""

    def test_generate_reply_result_success_contract_shape(self):
        from app.services.openai_service import generate_reply_result

        provider = Mock(return_value="Hello from AI")

        result = generate_reply_result(
            message_text="hello",
            wa_id="15551234567",
            name="Tester",
            agent_context={"name": "Ops"},
            request_id="req-ai-ok",
            provider=provider,
            metrics=None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["reply_text"], "Hello from AI")
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["request_id"], "req-ai-ok")
        self.assertIn("assistant_id", result["metadata"])
        self.assertIn("duration_seconds", result["metadata"])
        self.assertGreaterEqual(result["metadata"]["duration_seconds"], 0.0)
        provider.assert_called_once_with("hello", "15551234567", "Tester")

    def test_generate_reply_result_sanitizes_failure_detail(self):
        from app.services.openai_service import generate_reply_result

        def _provider_with_secret(message_text, wa_id, name):
            raise RuntimeError("provider failed with OPENAI_API_KEY=sk-live-1234567890")

        result = generate_reply_result(
            message_text="hello",
            wa_id="15551234567",
            name="Tester",
            request_id="req-ai-secret",
            provider=_provider_with_secret,
            metrics=None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "provider_error")
        self.assertIsInstance(result["error_detail"], str)
        self.assertIn("[REDACTED]", result["error_detail"])
        self.assertNotIn("sk-live-1234567890", result["error_detail"])

    def test_generate_reply_result_timeout_is_controlled_state(self):
        from app.services.openai_service import generate_reply_result

        def _timeout_provider(message_text, wa_id, name):
            raise TimeoutError("timed out waiting for provider")

        result = generate_reply_result(
            message_text="hello",
            wa_id="15551234567",
            name="Tester",
            request_id="req-ai-timeout",
            provider=_timeout_provider,
            metrics=None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["error_code"], "timeout")

    def test_generate_reply_result_auth_is_controlled_state(self):
        from app.services.openai_service import generate_reply_result

        class AuthenticationError(Exception):
            pass

        def _auth_provider(message_text, wa_id, name):
            raise AuthenticationError("unauthorized")

        result = generate_reply_result(
            message_text="hello",
            wa_id="15551234567",
            name="Tester",
            request_id="req-ai-auth",
            provider=_auth_provider,
            metrics=None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "auth_error")
        self.assertEqual(result["error_code"], "auth_error")

    def test_generate_reply_result_rate_limit_is_controlled_state(self):
        from app.services.openai_service import generate_reply_result

        class RateLimitError(Exception):
            pass

        def _rate_limit_provider(message_text, wa_id, name):
            raise RateLimitError("rate limit exceeded")

        result = generate_reply_result(
            message_text="hello",
            wa_id="15551234567",
            name="Tester",
            request_id="req-ai-rate",
            provider=_rate_limit_provider,
            metrics=None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(result["error_code"], "rate_limited")

    def test_process_message_uses_openai_provider_when_enabled(self):
        from app.utils.whatsapp_utils import process_whatsapp_message

        app = Flask(__name__)
        app.config.update(
            {
                "ACCESS_TOKEN": "token",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "USE_OPENAI_SERVICE": True,
                "OPENAI_ASSISTANT_ID": "asst_123",
            }
        )

        payload = {
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
                                    {
                                        "id": "wamid-openai-1",
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}):
                with patch("app.services.openai_service.generate_response", return_value="OpenAI says hi") as mock_openai:
                    with patch(
                        "app.utils.whatsapp_utils.send_message",
                        return_value={"status": "sent", "error": None, "operator_review_flagged": False},
                    ):
                        result = process_whatsapp_message(payload, request_id="req-openai")

        self.assertEqual(result["response_source"], "agent")
        self.assertEqual(result["reply_text"], "OpenAI says hi")
        mock_openai.assert_called_once_with(
            "hello",
            "15551234567",
            "Tester",
            {"name": "Ops"},
        )

    def test_generate_reply_result_records_metrics(self):
        from app.services.metrics import get_metrics_collector
        from app.services.openai_service import generate_reply_result

        app = Flask(__name__)
        with app.app_context():
            metrics = get_metrics_collector(app)
            generate_reply_result(
                message_text="hello",
                wa_id="15551234567",
                name="Tester",
                request_id="req-ai-metrics",
                provider=lambda message_text, wa_id, name: "ok",
                metrics=metrics,
            )
            snapshot = metrics.snapshot()

        self.assertGreaterEqual(snapshot["counters"]["ai.reply_attempt"], 1)
        self.assertGreaterEqual(snapshot["counters"]["ai.reply_success"], 1)
        self.assertGreaterEqual(snapshot["durations"]["counts"]["ai.reply_duration"], 1)

    def test_generate_reply_result_records_failure_metrics(self):
        from app.services.metrics import get_metrics_collector
        from app.services.openai_service import generate_reply_result

        app = Flask(__name__)
        with app.app_context():
            metrics = get_metrics_collector(app)

            def _timeout_provider(message_text, wa_id, name):
                raise TimeoutError("timed out")

            result = generate_reply_result(
                message_text="hello",
                wa_id="15551234567",
                name="Tester",
                request_id="req-ai-failure-metrics",
                provider=_timeout_provider,
                metrics=metrics,
            )
            snapshot = metrics.snapshot()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "timeout")
        self.assertGreaterEqual(snapshot["counters"]["ai.reply_attempt"], 1)
        self.assertGreaterEqual(snapshot["counters"]["ai.reply_timeout"], 1)
        self.assertGreaterEqual(snapshot["durations"]["counts"]["ai.reply_duration"], 1)

    def test_process_message_uses_ai_fallback_on_controlled_failure(self):
        from app.utils.whatsapp_utils import process_whatsapp_message

        app = Flask(__name__)
        app.config.update(
            {
                "ACCESS_TOKEN": "token",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
            }
        )

        payload = {
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
                                    {
                                        "id": "wamid-openai-fail-1",
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}), patch(
                "app.utils.whatsapp_utils._generate_reply_result",
                return_value={
                    "ok": False,
                    "status": "timeout",
                    "reply_text": None,
                    "confidence": None,
                    "metadata": {"request_id": "req-ai-failure"},
                    "error_code": "timeout",
                    "error_detail": "timed out",
                },
            ), patch(
                "app.utils.whatsapp_utils.send_message",
                return_value={"status": "sent", "error": None, "operator_review_flagged": False},
            ):
                result = process_whatsapp_message(payload, request_id="req-ai-failure")

        self.assertEqual(result["response_source"], "ai_fallback")
        self.assertEqual(result["ai_status"], "timeout")
        self.assertEqual(result["ai_error_code"], "timeout")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["error"], "ai_timeout:timeout")

    def test_process_message_uses_ai_fallback_on_metrics_error(self):
        from app.utils.whatsapp_utils import process_whatsapp_message

        app = Flask(__name__)
        app.config.update(
            {
                "ACCESS_TOKEN": "token",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
            }
        )

        payload = {
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
                                    {
                                        "id": "wamid-openai-metrics-fail-1",
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_selected_agent", return_value={"name": "Ops"}), patch(
                "app.utils.whatsapp_utils._generate_reply_result",
                return_value={
                    "ok": False,
                    "status": "metrics_error",
                    "reply_text": None,
                    "confidence": None,
                    "metadata": {"request_id": "req-ai-metrics-failure"},
                    "error_code": "metrics_error",
                    "error_detail": "metrics increment failure",
                },
            ), patch(
                "app.utils.whatsapp_utils.send_message",
                return_value={"status": "sent", "error": None, "operator_review_flagged": False},
            ):
                result = process_whatsapp_message(payload, request_id="req-ai-metrics-failure")

        self.assertEqual(result["response_source"], "ai_fallback")
        self.assertEqual(result["ai_status"], "metrics_error")
        self.assertEqual(result["ai_error_code"], "metrics_error")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["error"], "ai_metrics_error:metrics_error")

    def test_retryable_exception_classified_correctly(self):
        from app.services.openai_service import _is_retryable_exception

        class RateLimitError(Exception):
            pass

        class APIConnectionError(Exception):
            pass

        class APITimeoutError(Exception):
            pass

        self.assertTrue(_is_retryable_exception(RateLimitError("rate limit")))
        self.assertTrue(_is_retryable_exception(APIConnectionError("conn error")))
        self.assertTrue(_is_retryable_exception(APITimeoutError("timeout")))

    def test_non_retryable_exception_not_classified_as_retryable(self):
        from app.services.openai_service import _is_retryable_exception

        self.assertFalse(_is_retryable_exception(ValueError("bad input")))
        self.assertFalse(_is_retryable_exception(RuntimeError("assistant failed")))

    def test_string_based_timeout_detection(self):
        from app.services.openai_service import _is_retryable_exception

        self.assertTrue(_is_retryable_exception(Exception("request timeout exceeded")))
        self.assertTrue(_is_retryable_exception(Exception("temporary service issue")))
        self.assertTrue(_is_retryable_exception(Exception("rate limit exceeded")))


if __name__ == "__main__":
    unittest.main()
