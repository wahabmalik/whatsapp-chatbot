import hashlib
import hmac
import importlib
import json
import os
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
from typing import Optional

from flask import Flask, jsonify


REQUIRED_ENV = {
    "WHATSAPP_PROVIDER": "meta",
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


class ConfigValidationTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, REQUIRED_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_validate_config_missing_required_key(self):
        from app.config import load_configurations, validate_config

        app = Flask(__name__)
        load_configurations(app)
        app.config["ACCESS_TOKEN"] = ""

        errors = validate_config(app)
        self.assertTrue(any("ACCESS_TOKEN" in item for item in errors))

    def test_validate_config_rejects_bad_version(self):
        from app.config import load_configurations, validate_config

        app = Flask(__name__)
        load_configurations(app)
        app.config["VERSION"] = "18"

        errors = validate_config(app)
        self.assertTrue(any("VERSION" in item for item in errors))

    def test_create_app_warns_on_missing_config_but_does_not_raise(self):
        # AC3 Story 1.1: missing config must not crash the app; setup must stay reachable.
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv", return_value=None):
            from app import create_app

            app = create_app()
            self.assertIsNotNone(app)
            self.assertTrue(len(app.extensions.get("config_validation_errors", [])) > 0)


class SecurityDecoratorTests(unittest.TestCase):
    def setUp(self):
        from app.decorators import security

        self._env_patch = patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta"}, clear=False)
        self._env_patch.start()

        self.security = security
        security.clear_signature_replay_cache()

        self.app = Flask(__name__)
        self.app.config.update(
            {
                "WHATSAPP_PROVIDER": "meta",
                "APP_SECRET": "test-secret",
                "SIGNATURE_MAX_SKEW_SECONDS": 300,
                "SIGNATURE_REPLAY_WINDOW_SECONDS": 300,
            }
        )

        @self.app.route("/secured", methods=["POST"])
        @security.signature_required
        def secured():
            return jsonify({"status": "ok"}), 200

        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def _signature(self, payload: str) -> str:
        digest = hmac.new(
            b"test-secret", msg=payload.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"

    def test_rejects_invalid_signature(self):
        response = self.client.post(
            "/secured",
            data="{}",
            headers={"X-Hub-Signature-256": "sha256=bad"},
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_malformed_signature_header(self):
        response = self.client.post(
            "/secured",
            data="{}",
            headers={"X-Hub-Signature-256": "not-sha256-format"},
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_replay_signature(self):
        payload = "{}"
        signature = self._signature(payload)
        headers = {
            "X-Hub-Signature-256": signature,
            "X-Hub-Signature-Timestamp": "1700000000",
        }

        with patch("app.decorators.security.time.time", return_value=1700000010):
            first = self.client.post("/secured", data=payload, headers=headers)
            second = self.client.post("/secured", data=payload, headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 403)

    def test_rejects_old_timestamp(self):
        payload = "{}"
        signature = self._signature(payload)
        headers = {
            "X-Hub-Signature-256": signature,
            "X-Hub-Signature-Timestamp": "1000",
        }

        with patch("app.decorators.security.time.time", return_value=2000):
            response = self.client.post("/secured", data=payload, headers=headers)

        self.assertEqual(response.status_code, 403)


class WebhookIdempotencyTests(unittest.TestCase):
    def setUp(self):
        from app import views

        self.views = views
        views.clear_message_idempotency_cache()

    def _payload(self, message_id: str) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [
                                    {"wa_id": "15551234567", "profile": {"name": "Test"}}
                                ],
                                "messages": [
                                    {
                                        "id": message_id,
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ],
        }

    def _payload_with_context(self, *, body: str = "hello", timestamp: str = "1700000000", context_id: Optional[str] = None) -> dict:
        message = {
            "text": {"body": body},
            "timestamp": timestamp,
        }
        if context_id:
            message["context"] = {"id": context_id}

        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [
                                    {"wa_id": "15551234567", "profile": {"name": "Test"}}
                                ],
                                "messages": [
                                    message
                                ],
                            }
                        }
                    ]
                }
            ],
        }

    def test_duplicate_message_is_skipped(self):
        with patch("app.views.process_whatsapp_message") as mock_process:
            app = Flask(__name__)
            app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

            with app.test_request_context(json=self._payload("wamid-1")):
                first = self.views.handle_message()
            with app.test_request_context(json=self._payload("wamid-1")):
                second = self.views.handle_message()

        self.assertEqual(first[1], 200)
        self.assertEqual(second[1], 200)
        self.assertEqual(mock_process.call_count, 1)

    def test_duplicate_message_without_message_id_is_skipped(self):
        with patch("app.views.process_whatsapp_message") as mock_process:
            app = Flask(__name__)
            app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

            first_payload = self._payload_without_message_id(body="hello", timestamp="1700000010")
            second_payload = self._payload_without_message_id(body="hello", timestamp="1700000010")

            with app.test_request_context(json=first_payload):
                first = self.views.handle_message()
            with app.test_request_context(json=second_payload):
                second = self.views.handle_message()

        self.assertEqual(first[1], 200)
        self.assertEqual(second[1], 200)
        self.assertEqual(mock_process.call_count, 1)

    def test_missing_message_id_payload_variants_are_not_deduplicated(self):
        with patch("app.views.process_whatsapp_message") as mock_process:
            app = Flask(__name__)
            app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

            first_payload = self._payload_without_message_id(
                body="hello",
                timestamp="1700000010",
                context_id="ctx-1",
            )
            second_payload = self._payload_without_message_id(
                body="hello",
                timestamp="1700000010",
                context_id="ctx-2",
            )

            with app.test_request_context(json=first_payload):
                first = self.views.handle_message()
            with app.test_request_context(json=second_payload):
                second = self.views.handle_message()

        self.assertEqual(first[1], 200)
        self.assertEqual(second[1], 200)
        self.assertEqual(mock_process.call_count, 2)

    def test_processing_exception_returns_internal_error(self):
        with patch("app.views.process_whatsapp_message", side_effect=RuntimeError("boom")):
            app = Flask(__name__)
            app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

            with app.test_request_context(json=self._payload("wamid-2")):
                response = self.views.handle_message()

        self.assertEqual(response[1], 500)

    def test_duplicate_message_is_skipped_with_sqlite_store(self):
        with patch("app.views.process_whatsapp_message") as mock_process:
            with tempfile.TemporaryDirectory() as tmp_dir:
                app = Flask(__name__)
                app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300
                app.config["STATE_STORE_BACKEND"] = "sqlite"
                app.config["STATE_STORE_SQLITE_PATH"] = os.path.join(
                    tmp_dir, "runtime_state.db"
                )

                with app.test_request_context(json=self._payload("wamid-sqlite")):
                    first = self.views.handle_message()
                with app.test_request_context(json=self._payload("wamid-sqlite")):
                    second = self.views.handle_message()

                store = app.extensions.get("message_id_store")
                if store and hasattr(store, "close"):
                    store.close()

        self.assertEqual(first[1], 200)
        self.assertEqual(second[1], 200)
        self.assertEqual(mock_process.call_count, 1)

    def test_handle_message_logs_escalation_reason_fields(self):
        from app.services.message_log import get_message_log_buffer

        app = Flask(__name__)
        app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

        with patch(
            "app.views.process_whatsapp_message",
            return_value={
                "from": "15551234567",
                "message_id": "wamid-log-1",
                "agent": "Ops",
                "input_text": "Need human",
                "reply_text": "Routed",
                "status": "sent",
                "error": None,
                "operator_review_flagged": True,
                "operator_review_reason": "escalation_keyword",
            },
        ):
            with app.test_request_context(json=self._payload("wamid-log-1")):
                response = self.views.handle_message()

        self.assertEqual(response[1], 200)
        logs = get_message_log_buffer(app).get_all()
        self.assertGreaterEqual(len(logs), 1)
        self.assertTrue(logs[0].get("operator_review_flagged"))
        self.assertEqual(logs[0].get("operator_review_reason"), "escalation_keyword")


class InboundNormalizationTests(unittest.TestCase):
    def test_meta_text_message_normalizes_to_canonical_contract(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": "15551234567", "profile": {"name": "Tester"}}],
                                "messages": [
                                    {
                                        "id": "wamid-norm-1",
                                        "timestamp": "1714500000",
                                        "type": "text",
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ],
        }

        inbound = normalize_inbound_message(payload)
        self.assertIsNotNone(inbound)
        self.assertEqual(inbound["user_id"], "15551234567")
        self.assertEqual(inbound["message_text"], "hello")
        self.assertEqual(inbound["timestamp"], "1714500000")
        self.assertEqual(inbound["message_id"], "wamid-norm-1")

    def test_meta_non_text_message_is_marked_unsupported(self):
        from app.utils.whatsapp_utils import normalize_inbound_message

        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": "15551234567", "profile": {"name": "Tester"}}],
                                "messages": [
                                    {
                                        "id": "wamid-image-1",
                                        "type": "image",
                                        "image": {"id": "img-1"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ],
        }

        inbound = normalize_inbound_message(payload)
        self.assertIsNotNone(inbound)
        self.assertTrue(inbound["unsupported"])
        self.assertEqual(inbound["unsupported_reason"], "non_text_message")


class UnsupportedInboundWebhookHandlingTests(unittest.TestCase):
    def setUp(self):
        from app import views

        self.views = views

    def _non_text_payload(self) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": "15551234567", "profile": {"name": "Tester"}}],
                                "messages": [{"id": "wamid-unsupported-1", "type": "image", "image": {"id": "img-1"}}],
                            }
                        }
                    ]
                }
            ],
        }

    def test_unsupported_non_text_payload_returns_handled_ack_and_skips_downstream(self):
        app = Flask(__name__)
        app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

        with patch("app.views.process_whatsapp_message") as mock_process:
            with app.test_request_context(json=self._non_text_payload()):
                response = self.views.handle_message()

        self.assertEqual(response[1], 200)
        payload = response[0].get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["handled"])
        self.assertEqual(payload["reason"], "non_text_message")
        self.assertIn("correlation_id", payload)
        mock_process.assert_not_called()


class InstagramWebhookE2ETests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(
            os.environ,
            {
                **REQUIRED_ENV,
                "OUTBOUND_CHANNEL": "instagram",
                "INSTAGRAM_OUTBOUND_URL": "https://example.com/instagram/messages",
                "INSTAGRAM_DEFAULT_RECIPIENT_ID": "17841400008460056",
            },
            clear=False,
        )
        self._env_patch.start()

        from app import views

        self.views = views
        views.clear_message_idempotency_cache()

    def tearDown(self):
        self._env_patch.stop()

    def _payload(self) -> dict:
        return {
            "object": "instagram",
            "entry": [
                {
                    "id": "17841499999999999",
                    "messaging": [
                        {
                            "sender": {"id": "17841400008460056"},
                            "recipient": {"id": "17841499999999999"},
                            "timestamp": 1700000002,
                            "message": {
                                "mid": "ig-mid-e2e-001",
                                "text": "hello from instagram e2e",
                            },
                        }
                    ],
                }
            ],
        }

    def test_handle_message_processes_instagram_payload_end_to_end(self):
        from app import create_app

        app = create_app()
        captured: dict[str, object] = {}

        class _FakeChannel:
            def send(self, data, *, request_id, delivery_context=None):
                captured["data"] = data
                captured["request_id"] = request_id
                captured["delivery_context"] = delivery_context
                return {
                    "ok": True,
                    "status": "sent",
                    "error": None,
                    "fallback_sent": False,
                    "operator_review_flagged": False,
                    "operator_review_reason": None,
                    "attempts": 1,
                }

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=_FakeChannel()):
                with patch(
                    "app.utils.whatsapp_utils._generate_reply_result",
                    return_value={
                        "ok": True,
                        "reply_text": "instagram reply",
                        "confidence": 0.9,
                        "status": "ok",
                        "error_code": None,
                        "metadata": None,
                    },
                ):
                    with app.test_request_context(json=self._payload()):
                        response = self.views.handle_message()

        self.assertEqual(response[1], 200)
        payload = response[0].get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("correlation_id", payload)
        self.assertEqual(captured["delivery_context"]["recipient_id"], "17841400008460056")
        self.assertEqual(captured["delivery_context"]["instagram_recipient_id"], "17841400008460056")
        self.assertEqual(captured["delivery_context"]["wa_id"], "17841400008460056")

    def test_handle_message_skips_duplicate_instagram_message(self):
        app = Flask(__name__)
        app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

        with patch(
            "app.views.process_whatsapp_message",
            return_value={
                "from": "17841400008460056",
                "message_id": "ig-mid-e2e-001",
                "agent": "Ops",
                "input_text": "hello from instagram e2e",
                "reply_text": "instagram reply",
                "status": "sent",
                "error": None,
                "operator_review_flagged": False,
                "operator_review_reason": None,
            },
        ) as mock_process:
            with app.test_request_context(json=self._payload()):
                first = self.views.handle_message()
            with app.test_request_context(json=self._payload()):
                second = self.views.handle_message()

        self.assertEqual(first[1], 200)
        self.assertEqual(second[1], 200)
        self.assertEqual(mock_process.call_count, 1)
        self.assertTrue(second[0].get_json()["duplicate"])


class MessengerWebhookE2ETests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(
            os.environ,
            {
                **REQUIRED_ENV,
                "OUTBOUND_CHANNEL": "messenger",
                "MESSENGER_OUTBOUND_URL": "https://example.com/messenger/messages",
                "MESSENGER_DEFAULT_RECIPIENT_ID": "1234567890123456",
            },
            clear=False,
        )
        self._env_patch.start()

        from app import views

        self.views = views
        views.clear_message_idempotency_cache()

    def tearDown(self):
        self._env_patch.stop()

    def _payload(self) -> dict:
        return {
            "object": "page",
            "entry": [
                {
                    "id": "9876543210987654",
                    "messaging": [
                        {
                            "sender": {"id": "1234567890123456"},
                            "recipient": {"id": "9876543210987654"},
                            "timestamp": 1700000003,
                            "message": {
                                "mid": "m-mid-e2e-001",
                                "text": "hello from messenger e2e",
                            },
                        }
                    ],
                }
            ],
        }

    def test_handle_message_processes_messenger_payload_end_to_end(self):
        from app import create_app

        app = create_app()
        captured: dict[str, object] = {}

        class _FakeChannel:
            def send(self, data, *, request_id, delivery_context=None):
                captured["data"] = data
                captured["request_id"] = request_id
                captured["delivery_context"] = delivery_context
                return {
                    "ok": True,
                    "status": "sent",
                    "error": None,
                    "fallback_sent": False,
                    "operator_review_flagged": False,
                    "operator_review_reason": None,
                    "attempts": 1,
                }

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=_FakeChannel()):
                with patch(
                    "app.utils.whatsapp_utils._generate_reply_result",
                    return_value={
                        "ok": True,
                        "reply_text": "messenger reply",
                        "confidence": 0.9,
                        "status": "ok",
                        "error_code": None,
                        "metadata": None,
                    },
                ):
                    with app.test_request_context(json=self._payload()):
                        response = self.views.handle_message()

        self.assertEqual(response[1], 200)
        payload = response[0].get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("correlation_id", payload)
        self.assertEqual(captured["delivery_context"]["recipient_id"], "1234567890123456")
        self.assertEqual(captured["delivery_context"]["messenger_recipient_id"], "1234567890123456")
        self.assertEqual(captured["delivery_context"]["wa_id"], "1234567890123456")

    def test_handle_message_skips_duplicate_messenger_message(self):
        app = Flask(__name__)
        app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300

        with patch(
            "app.views.process_whatsapp_message",
            return_value={
                "from": "1234567890123456",
                "message_id": "m-mid-e2e-001",
                "agent": "Ops",
                "input_text": "hello from messenger e2e",
                "reply_text": "messenger reply",
                "status": "sent",
                "error": None,
                "operator_review_flagged": False,
                "operator_review_reason": None,
            },
        ) as mock_process:
            with app.test_request_context(json=self._payload()):
                first = self.views.handle_message()
            with app.test_request_context(json=self._payload()):
                second = self.views.handle_message()

        self.assertEqual(first[1], 200)
        self.assertEqual(second[1], 200)
        self.assertEqual(mock_process.call_count, 1)
        self.assertTrue(second[0].get_json()["duplicate"])


class MetricsEndpointTests(unittest.TestCase):
    def test_metrics_endpoint_returns_snapshot(self):
        from app.views import webhook_blueprint
        from app.views_dashboard import dashboard_blueprint

        app = Flask(__name__)
        app.register_blueprint(webhook_blueprint)
        app.register_blueprint(dashboard_blueprint)

        client = app.test_client()
        response = client.get("/api/metrics")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("counters", payload)
        self.assertIn("durations", payload)


class DashboardRouteGuardTests(unittest.TestCase):
    def setUp(self):
        from app.views_dashboard import dashboard_blueprint
        from app.onboarding import onboarding_blueprint

        self.app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
        self.app.config.update(
            {
                "SECRET_KEY": "test-secret",
                "WHATSAPP_PROVIDER": "meta",
                "ACCESS_TOKEN": "token",
                "APP_SECRET": "app-secret",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "VERIFY_TOKEN": "verify-token",
                "OPENAI_API_KEY": "openai-key",
            }
        )
        self.app.register_blueprint(dashboard_blueprint)
        self.app.register_blueprint(onboarding_blueprint)
        self.client = self.app.test_client()

    def _assert_redirect_next(self, location: str, expected_next: str) -> None:
        parsed = urlparse(location)
        self.assertEqual(parsed.path, "/operator/access")
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("next"), [expected_next])

    def _csrf_headers(self) -> dict[str, str]:
        token = "test-csrf-token"
        with self.client.session_transaction() as session:
            session["_csrf_token"] = token
        return {"X-CSRFToken": token}

    def test_operator_route_redirects_to_operator_access_for_end_user_mode(self):
        response = self.client.get("/operator/metrics", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self._assert_redirect_next(response.headers["Location"], "/operator/metrics")

    def test_operator_access_rejects_external_redirect_targets(self):
        response = self.client.get(
            "/operator/access?next=https://evil.example/steal",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/operator"))

    def test_operator_access_rejects_protocol_relative_redirect_targets(self):
        response = self.client.get(
            "/operator/access?next=//evil.example/steal",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/operator"))

    def test_operator_access_allows_safe_redirect_targets(self):
        response = self.client.get("/operator/access?next=/logs", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/logs"))

    def test_agents_route_redirects_to_operator_access_for_end_user_mode(self):
        response = self.client.get("/agents", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self._assert_redirect_next(response.headers["Location"], "/agents")

    def test_agents_post_returns_structured_error_when_save_fails(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        with patch(
            "app.views_dashboard.list_bmad_agents",
            return_value=[{"code": "bmad-agent-dev", "name": "Amelia"}],
        ), patch("app.views_dashboard.set_selected_agent_code", side_effect=OSError("disk error")):
            response = self.client.post(
                "/agents",
                data={"agent_code": "bmad-agent-dev"},
                headers=self._csrf_headers(),
            )

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("Could not save", payload["message"])

    def test_agents_page_single_agent_preselects_and_disables_save(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        with patch(
            "app.views_dashboard.list_bmad_agents",
            return_value=[
                {
                    "code": "whatsapp-support-ops",
                    "name": "Nia",
                    "title": "WhatsApp Support Ops Specialist",
                    "description": "Single installed agent",
                }
            ],
        ), patch("app.views_dashboard.get_selected_agent_code", return_value="whatsapp-support-ops"):
            response = self.client.get("/agents")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="whatsapp-support-ops" checked', response.data)
        self.assertIn(b'id="save-agent" type="submit" disabled', response.data)

    def test_customer_dashboard_renders_social_connect_buttons(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Connect Instagram", html)
        self.assertIn("Connect Facebook Messenger", html)
        self.assertIn("Connect TikTok", html)

    def test_customer_dashboard_uses_configured_connect_urls(self):
        self.app.config["INSTAGRAM_CONNECT_URL"] = "https://example.com/instagram/connect"
        self.app.config["MESSENGER_CONNECT_URL"] = "https://example.com/messenger/connect"
        self.app.config["TIKTOK_CONNECT_URL"] = "https://example.com/tiktok/connect"

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("https://example.com/instagram/connect", html)
        self.assertIn("https://example.com/messenger/connect", html)
        self.assertIn("https://example.com/tiktok/connect", html)

    def test_customer_dashboard_rejects_unsafe_connect_urls(self):
        self.app.config["INSTAGRAM_CONNECT_URL"] = "javascript:alert(1)"

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("javascript:alert(1)", html)
        self.assertIn("/operator/access", html)

    def test_operator_post_guard_returns_json_redirect(self):
        response = self.client.post("/setup/verify")

        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertEqual(payload["ok"], False)
        self._assert_redirect_next(payload["redirect_to"], "/setup/verify")

    def test_operator_copy_mentions_setup_on_empty_logs(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        response = self.client.get("/logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Finish setup and send a test WhatsApp message", response.data)

    def test_operator_dashboard_renders_bottom_nav(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        response = self.client.get("/operator")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"bottom-nav", response.data)

    def test_setup_route_sets_current_step_to_validate_when_incomplete(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        # Need at least 2 keys missing so present_count < max(2, total-1=5) → step 2
        self.app.config["ACCESS_TOKEN"] = ""
        self.app.config["APP_SECRET"] = ""
        response = self.client.get("/setup")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<li aria-current="step">Validate required keys</li>', response.data)

    def test_setup_route_sets_current_step_to_finish_when_complete(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        response = self.client.get("/setup")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<li aria-current="step">Verify webhook access</li>', response.data)

    def test_setup_route_sets_current_step_to_copy_when_near_complete(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        self.app.config["ACCESS_TOKEN"] = ""
        response = self.client.get("/setup")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<li aria-current="step">Copy webhook URL</li>', response.data)

    def test_setup_route_sets_current_step_to_finish_after_verify(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        verify_response = self.client.post("/setup/verify", headers=self._csrf_headers())
        self.assertEqual(verify_response.status_code, 200)

        response = self.client.get("/setup")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<li aria-current="step">Finish</li>', response.data)

    def test_setup_save_openai_key_persists_and_refreshes_live_client(self):
        with self.client.session_transaction() as session:
            session["dashboard_role"] = "operator"

        saved = ""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as env_file:
                env_file.write("VERIFY_TOKEN=verify-token\nEXTRA_KEY=keep-me\n")

            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            with patch("app.services.openai_service.refresh_openai_client") as mock_refresh:
                response = self.client.post(
                    "/setup/openai-key",
                    data={"openai_api_key": "sk-live-updated"},
                    headers=self._csrf_headers(),
                )

            with open(env_path, "r", encoding="utf-8") as env_file:
                saved = env_file.read()

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("applied", payload["message"])
        mock_refresh.assert_called_once_with("sk-live-updated")
        self.assertIn('OPENAI_API_KEY="sk-live-updated"', saved)
        self.assertIn("VERIFY_TOKEN=verify-token", saved)
        self.assertIn("EXTRA_KEY=keep-me", saved)


class ConversationContextTests(unittest.TestCase):
    """Story 3.3 AC1 — per-user rolling context window."""

    def setUp(self):
        from app.services.conversation_context import ConversationContextStore
        self.Store = ConversationContextStore

    def test_get_context_empty_for_unknown_user(self):
        store = self.Store()
        self.assertEqual(store.get_context("user1"), [])

    def test_append_stores_message(self):
        store = self.Store()
        store.append_message("user1", {"role": "user", "text": "hello"})
        ctx = store.get_context("user1")
        self.assertEqual(len(ctx), 1)
        self.assertEqual(ctx[0]["text"], "hello")

    def test_sixth_message_evicts_oldest(self):
        store = self.Store()
        for i in range(6):
            store.append_message("user1", {"role": "user", "text": f"msg{i}"})
        ctx = store.get_context("user1")
        self.assertEqual(len(ctx), 5)
        # oldest (msg0) should be gone; msg1 is now first
        texts = [m["text"] for m in ctx]
        self.assertNotIn("msg0", texts)
        self.assertIn("msg5", texts)

    def test_reset_context_clears_user(self):
        store = self.Store()
        store.append_message("user1", {"role": "user", "text": "hello"})
        store.reset_context("user1")
        self.assertEqual(store.get_context("user1"), [])

    def test_reset_context_on_nonexistent_user_is_safe(self):
        store = self.Store()
        store.reset_context("nobody")  # must not raise

    def test_clear_removes_all_users(self):
        store = self.Store()
        store.append_message("user1", {"role": "user", "text": "a"})
        store.append_message("user2", {"role": "user", "text": "b"})
        store.clear()
        self.assertEqual(store.get_context("user1"), [])
        self.assertEqual(store.get_context("user2"), [])

    def test_timeout_resets_context_on_next_append(self):
        """A second append after timeout starts a fresh window."""
        from unittest.mock import patch
        store = self.Store(timeout_seconds=1.0)
        store.append_message("user1", {"role": "user", "text": "old"})
        # Simulate monotonic clock advancing past timeout
        future_time = store._store["user1"]["last_activity"] + 2.0
        with patch("app.services.conversation_context.monotonic", return_value=future_time):
            store.append_message("user1", {"role": "user", "text": "new"})
        ctx = store.get_context("user1")
        self.assertEqual(len(ctx), 1)
        self.assertEqual(ctx[0]["text"], "new")

    def test_get_context_returns_empty_after_timeout(self):
        from unittest.mock import patch
        store = self.Store(timeout_seconds=1.0)
        store.append_message("user1", {"role": "user", "text": "old"})
        future_time = store._store["user1"]["last_activity"] + 2.0
        with patch("app.services.conversation_context.monotonic", return_value=future_time):
            ctx = store.get_context("user1")
        self.assertEqual(ctx, [])

    def test_app_extension_accessor_creates_and_reuses(self):
        from app.services.conversation_context import get_conversation_context_store
        from flask import Flask
        app = Flask(__name__)
        app.config["CONVERSATION_CONTEXT_TIMEOUT_SECONDS"] = 300
        store1 = get_conversation_context_store(app)
        store2 = get_conversation_context_store(app)
        self.assertIs(store1, store2)

    def test_webhook_appends_context_on_message(self):
        from app import views
        from app.services.conversation_context import get_conversation_context_store

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {
                "contacts": [{"wa_id": "15551234567", "profile": {"name": "Tester"}}],
                "messages": [{"id": "wamid-ctx-1", "text": {"body": "context message"}}],
            }}]}],
        }

        with patch(
            "app.views.process_whatsapp_message",
            return_value={
                "from": "15551234567",
                "message_id": "wamid-ctx-1",
                "agent": "Bot",
                "input_text": "context message",
                "reply_text": "reply",
                "status": "sent",
                "error": None,
                "operator_review_flagged": False,
                "operator_review_reason": None,
            },
        ):
            app = Flask(__name__)
            app.config["IDEMPOTENCY_WINDOW_SECONDS"] = 300
            with app.test_request_context(json=payload):
                views.handle_message()

        ctx = get_conversation_context_store(app).get_context("15551234567")
        self.assertEqual(len(ctx), 1)
        self.assertEqual(ctx[0]["text"], "context message")


class LogsViewTests(unittest.TestCase):
    """Story 3.3 AC3/AC4 — logs filtering, masking, reveal semantics."""

    def setUp(self):
        from app.views_dashboard import dashboard_blueprint
        from app.services.message_log import get_message_log_buffer

        self.app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
        self.app.config.update(
            {
                "SECRET_KEY": "test-secret",
                "ACCESS_TOKEN": "token",
                "APP_SECRET": "app-secret",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "VERIFY_TOKEN": "verify-token",
                "OPENAI_API_KEY": "openai-key",
            }
        )
        self.app.register_blueprint(dashboard_blueprint)

        # Pre-populate log buffer with known entries
        buf = get_message_log_buffer(self.app)
        buf.clear()
        buf.add_message({"timestamp": "2026-04-30T10:00:00", "from": "15551234567", "status": "sent",
                         "agent": "Bot", "preview": "hello", "reply_text": "hi", "error": None,
                         "operator_review_flagged": False, "operator_review_reason": None, "message_id": "m1"})
        buf.add_message({"timestamp": "2026-04-30T10:01:00", "from": "15557654321", "status": "error",
                         "agent": "Bot", "preview": "fail", "reply_text": None, "error": "Timeout",
                         "operator_review_flagged": False, "operator_review_reason": None, "message_id": "m2"})

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def test_logs_all_filter_returns_both_entries(self):
        response = self.client.get("/logs?status=all")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"15551234567", response.data)  # masked portion check via raw from field in template logic

    def test_logs_sent_filter_excludes_error_entries(self):
        response = self.client.get("/logs?status=sent")
        self.assertEqual(response.status_code, 200)
        # error entry's preview should not appear
        self.assertNotIn(b">fail<", response.data)

    def test_logs_error_filter_excludes_sent_entries(self):
        response = self.client.get("/logs?status=error")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b">hello<", response.data)

    def test_logs_masks_phone_number_by_default(self):
        response = self.client.get("/logs")
        self.assertEqual(response.status_code, 200)
        # Masked number format e.g. "155...4567" should be present
        self.assertIn(b"155...4567", response.data)
        # Full number should be in a hidden span, not the masked span
        body = response.get_data(as_text=True)
        # The full number must not appear in a data-masked element
        # Verify the reveal button exists with aria-expanded="false"
        self.assertIn('data-reveal-number', body)
        self.assertIn('aria-expanded="false"', body)

    def test_logs_expand_button_has_aria_expanded_false(self):
        response = self.client.get("/logs")
        body = response.get_data(as_text=True)
        self.assertIn('data-toggle-detail', body)
        self.assertIn('aria-expanded="false"', body)

    def test_logs_detail_row_hidden_by_default(self):
        response = self.client.get("/logs")
        body = response.get_data(as_text=True)
        # detail rows should have class="hide" initially
        self.assertIn('class="hide"', body)
        self.assertIn('data-detail-row', body)

    def test_logs_fifo_cap_preserved(self):
        from app.services.message_log import MessageLogBuffer
        buf = MessageLogBuffer(max_size=100)
        for i in range(110):
            buf.add_message({"id": i})
        self.assertEqual(len(buf.get_all()), 100)

    def test_logs_newest_first_ordering(self):
        from app.services.message_log import MessageLogBuffer
        buf = MessageLogBuffer(max_size=100)
        buf.add_message({"seq": 1})
        buf.add_message({"seq": 2})
        entries = buf.get_all()
        self.assertEqual(entries[0]["seq"], 2)
        self.assertEqual(entries[1]["seq"], 1)


class OperatorMobileNavTests(unittest.TestCase):
    """Mobile nav contract — bottom nav present for all operator page_key values."""

    def setUp(self):
        from app.views_dashboard import dashboard_blueprint

        self.app = Flask(__name__, template_folder="../app/templates", static_folder="../app/static")
        self.app.config.update(
            {
                "SECRET_KEY": "test-secret",
                "WHATSAPP_PROVIDER": "meta",
                "ACCESS_TOKEN": "token",
                "APP_SECRET": "app-secret",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "1234567890",
                "VERIFY_TOKEN": "verify-token",
                "OPENAI_API_KEY": "openai-key",
            }
        )
        self.app.register_blueprint(dashboard_blueprint)
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def _assert_bottom_nav_links(self, response):
        body = response.get_data(as_text=True)
        self.assertIn('class="bottom-nav"', body)
        self.assertIn('/operator', body)
        self.assertIn('/setup', body)
        self.assertIn('/agents', body)
        self.assertIn('/metrics', body)
        self.assertIn('/logs', body)

    def test_operator_dashboard_has_bottom_nav(self):
        response = self.client.get("/operator")
        self.assertEqual(response.status_code, 200)
        self._assert_bottom_nav_links(response)

    def test_metrics_page_has_bottom_nav(self):
        response = self.client.get("/operator/metrics")
        self.assertEqual(response.status_code, 200)
        self._assert_bottom_nav_links(response)

    def test_logs_page_has_bottom_nav(self):
        response = self.client.get("/logs")
        self.assertEqual(response.status_code, 200)
        self._assert_bottom_nav_links(response)

    def test_mobile_nav_present_for_all_operator_page_keys(self):
        page_routes = {
            "dashboard": "/operator",
            "metrics": "/operator/metrics",
            "logs": "/logs",
            "agents": "/agents",
            "setup": "/setup",
        }

        for page_key, route in page_routes.items():
            with self.subTest(page_key=page_key, route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self._assert_bottom_nav_links(response)


class OpenAIServiceReliabilityTests(unittest.TestCase):
    def setUp(self):
        from app.services import openai_service
        self.module = importlib.reload(openai_service)

    def test_wait_for_terminal_run_state_times_out(self):
        class FakeRun:
            def __init__(self, status):
                self.status = status

        with patch.object(self.module, "RUN_TIMEOUT_SECONDS", 0.1), patch.object(
            self.module, "POLL_INTERVAL_SECONDS", 0.01
        ), patch.object(
            self.module,
            "_retrieve_run_with_retries",
            return_value=FakeRun("in_progress"),
        ):
            with self.assertRaises(TimeoutError):
                self.module._wait_for_terminal_run_state("thread", "run")


if __name__ == "__main__":
    unittest.main()
