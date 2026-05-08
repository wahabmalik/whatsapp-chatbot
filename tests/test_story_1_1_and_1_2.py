"""
Tests for Story 1.1: Startup Validation and Setup Gating
Tests for Story 1.2: Webhook Verification and Signature Enforcement
"""
import hashlib
import hmac
import os
import unittest
from unittest.mock import patch

from flask import Flask


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

EVOLUTION_REQUIRED_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "https://evolution.example.com",
    "EVOLUTION_API_KEY": "evo-key",
    "EVOLUTION_INSTANCE_NAME": "bot-instance",
    "OPENAI_API_KEY": "sk-test-key",
    "RECIPIENT_WAID": "15551234567",
}


# ---------------------------------------------------------------------------
# Story 1.1 – Startup Validation and Setup Gating
# ---------------------------------------------------------------------------

class StartupValidationTests(unittest.TestCase):
    """AC1 – all required env vars checked for presence and non-empty value."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_validate_config_reports_every_missing_required_key(self):
        """AC1: each missing key produces a distinct error entry."""
        from app.config import load_configurations, validate_config

        app = Flask(__name__)
        load_configurations(app)
        for key in (
            "ACCESS_TOKEN",
            "APP_SECRET",
            "OPENAI_API_KEY",
            "VERIFY_TOKEN",
            "PHONE_NUMBER_ID",
        ):
            app.config[key] = ""

        errors = validate_config(app)
        for key in ("ACCESS_TOKEN", "APP_SECRET", "OPENAI_API_KEY", "VERIFY_TOKEN"):
            self.assertTrue(
                any(key in e for e in errors),
                f"Expected error for {key} but got: {errors}",
            )

    def test_validate_config_rejects_bad_version_format(self):
        """AC1: VERSION must match v<major>.<minor> pattern."""
        from app.config import load_configurations, validate_config

        app = Flask(__name__)
        load_configurations(app)
        app.config["VERSION"] = "18"

        errors = validate_config(app)
        self.assertTrue(any("VERSION" in e for e in errors))

    def test_validate_config_rejects_non_numeric_phone_number_id(self):
        """AC1: PHONE_NUMBER_ID must be digits only."""
        from app.config import load_configurations, validate_config

        app = Flask(__name__)
        load_configurations(app)
        app.config["PHONE_NUMBER_ID"] = "abc-not-numeric"

        errors = validate_config(app)
        self.assertTrue(any("PHONE_NUMBER_ID" in e for e in errors))

    def test_validate_config_passes_on_complete_valid_config(self):
        """AC1/AC2: valid config produces no errors."""
        from app.config import load_configurations, validate_config

        app = Flask(__name__)
        load_configurations(app)

        errors = validate_config(app)
        self.assertEqual(errors, [])

    def test_validate_config_treats_none_values_as_missing(self):
        """AC1: None-valued required settings must be treated as missing."""
        from app.config import load_configurations, validate_config

        app = Flask(__name__)
        load_configurations(app)
        app.config["OPENAI_API_KEY"] = None
        app.config["ACCESS_TOKEN"] = None

        errors = validate_config(app)
        self.assertTrue(any("OPENAI_API_KEY" in e for e in errors))
        self.assertTrue(any("ACCESS_TOKEN" in e for e in errors))

    def test_create_app_does_not_raise_on_missing_required_config(self):
        """AC3: missing config must NOT crash the app; setup must stay reachable."""
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv", return_value=None):
            from app import create_app

            app = create_app()
            self.assertIsNotNone(app)

    def test_create_app_sets_config_validation_errors_when_config_incomplete(self):
        """AC3: config_validation_errors extension is populated so routes can act on it."""
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv", return_value=None):
            from app import create_app

            app = create_app()
            errors = app.extensions.get("config_validation_errors", [])
            self.assertGreater(len(errors), 0)

    def test_create_app_has_no_config_validation_errors_on_complete_config(self):
        """AC3: complete config produces empty validation errors."""
        from app import create_app

        app = create_app()
        errors = app.extensions.get("config_validation_errors", [])
        self.assertEqual(errors, [])

    def test_create_app_logs_per_variable_readiness_without_values(self):
        """AC2: startup emits per-key readiness logging without exposing values."""
        with patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta", "OPENAI_API_KEY": "sk-secret"}, clear=True), patch(
            "app.config.load_dotenv", return_value=None
        ), patch("app.config.configure_logging", return_value=None), patch("app.logging.info") as mock_info:
            from app import create_app

            create_app()

        rendered = [
            str(call.args[0]) % tuple(call.args[1:]) if len(call.args) > 1 else str(call.args[0])
            for call in mock_info.call_args_list
        ]
        log_text = "\n".join(rendered)
        self.assertIn("CONFIG_READINESS key=OPENAI_API_KEY", log_text)
        self.assertNotIn("sk-secret", log_text)

    def test_validate_config_allows_evolution_without_meta_keys(self):
        """Evolution mode should only require Evolution transport settings."""
        from app.config import load_configurations, validate_config

        with patch.dict(os.environ, EVOLUTION_REQUIRED_ENV, clear=True):
            app = Flask(__name__)
            load_configurations(app)

        errors = validate_config(app)
        self.assertEqual(errors, [])


class SetupRouteTests(unittest.TestCase):
    """AC4 – /setup renders live pass/fail status for required keys."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta"}, clear=True)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def _make_client(self, config_overrides=None):
        from app.views import webhook_blueprint
        from app.views_dashboard import dashboard_blueprint

        app = Flask(
            __name__,
            template_folder="../app/templates",
            static_folder="../app/static",
        )
        base_config = {
            "SECRET_KEY": "test-secret",
            "WHATSAPP_PROVIDER": "meta",
            "ACCESS_TOKEN": "token",
            "APP_SECRET": "app-secret",
            "VERSION": "v18.0",
            "PHONE_NUMBER_ID": "1234567890",
            "VERIFY_TOKEN": "verify-token",
            "OPENAI_API_KEY": "openai-key",
        }
        if config_overrides:
            base_config.update(config_overrides)
        app.config.update(base_config)
        app.register_blueprint(webhook_blueprint)
        app.register_blueprint(dashboard_blueprint)
        client = app.test_client()
        # Elevate to operator so /setup is accessible
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
        return client

    def _csrf_headers(self, client):
        token = "test-csrf-token"
        with client.session_transaction() as sess:
            sess["_csrf_token"] = token
        return {"X-CSRFToken": token}

    def test_setup_route_renders_when_all_keys_present(self):
        """AC4: /setup renders a 200 when all required keys are configured."""
        client = self._make_client()
        response = client.get("/setup")
        self.assertEqual(response.status_code, 200)

    def test_setup_route_renders_when_keys_are_missing(self):
        """AC3/AC4: /setup must render (not 500) even when keys are absent."""
        client = self._make_client({"ACCESS_TOKEN": "", "APP_SECRET": ""})
        response = client.get("/setup")
        self.assertEqual(response.status_code, 200)

    def test_setup_verify_returns_structured_error_on_missing_keys(self):
        """AC5: /setup/verify returns actionable JSON error, not a stack trace."""
        client = self._make_client({"ACCESS_TOKEN": "", "VERIFY_TOKEN": ""})
        response = client.post("/setup/verify", headers=self._csrf_headers(client))
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("missing", payload)
        self.assertIsInstance(payload["missing"], list)
        self.assertGreater(len(payload["missing"]), 0)

    def test_setup_verify_returns_success_when_all_keys_present(self):
        """AC5: /setup/verify returns structured success when configuration is complete."""
        client = self._make_client()
        response = client.post("/setup/verify", headers=self._csrf_headers(client))
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])

    def test_setup_verify_reports_missing_when_value_is_none(self):
        """AC4/AC5: None-valued required keys are treated as missing in setup checks."""
        client = self._make_client({"OPENAI_API_KEY": None})
        response = client.post("/setup/verify", headers=self._csrf_headers(client))

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("OPENAI_API_KEY", payload["missing"])

    def test_setup_complete_cta_targets_operator_dashboard(self):
        """Story 3.2 AC2: setup completion should route to operator dashboard mode."""
        client = self._make_client()
        response = client.get("/setup")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/operator"', response.data)

    def test_setup_route_exposes_setup_status_endpoint_for_guidance(self):
        """Setup page wires the dynamic setup-status endpoint for guided completion messaging."""
        client = self._make_client()
        response = client.get("/setup")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-setup-status-url="/setup-status"', response.data)

    def test_setup_status_returns_next_steps_list(self):
        """Setup status API includes operator next steps and structured summary counts."""
        client = self._make_client({"ACCESS_TOKEN": "", "APP_SECRET": ""})
        response = client.get("/setup-status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("next_steps", payload)
        self.assertIsInstance(payload["next_steps"], list)
        self.assertGreater(len(payload["next_steps"]), 0)
        self.assertIn("summary", payload)
        self.assertGreater(payload["summary"].get("missing", 0), 0)


# ---------------------------------------------------------------------------
# Story 1.2 – Webhook Verification and Signature Enforcement
# ---------------------------------------------------------------------------

class WebhookVerifyTests(unittest.TestCase):
    """AC1 / AC2 – GET /webhook challenge-response and rejection paths."""

    def setUp(self):
        from app.views import webhook_blueprint

        self._env_patch = patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta"}, clear=True)
        self._env_patch.start()

        self.app = Flask(__name__)
        self.app.config["VERIFY_TOKEN"] = "my-secret-token"
        self.app.config["WHATSAPP_PROVIDER"] = "meta"
        self.app.register_blueprint(webhook_blueprint)
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def test_verify_returns_200_with_challenge_on_valid_subscribe(self):
        """AC1: valid mode + matching token → 200 + challenge echoed."""
        response = self.client.get(
            "/webhook",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "my-secret-token",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"abc123", response.data)

    def test_verify_returns_403_on_token_mismatch(self):
        """AC1/AC2: mismatched token → 403 Forbidden, no secret leaked."""
        response = self.client.get(
            "/webhook",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"my-secret-token", response.data)

    def test_verify_returns_403_on_wrong_mode(self):
        """AC2: non-subscribe mode with correct token → 403."""
        response = self.client.get(
            "/webhook",
            query_string={
                "hub.mode": "unsubscribe",
                "hub.verify_token": "my-secret-token",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_verify_returns_403_on_missing_params(self):
        """AC2: missing mode or token → 403 (not 400), no secret leaked."""
        response = self.client.get("/webhook")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"my-secret-token", response.data)

    def test_verify_returns_403_on_missing_token_only(self):
        """AC2: mode present but token absent → 403."""
        response = self.client.get(
            "/webhook",
            query_string={"hub.mode": "subscribe"},
        )
        self.assertEqual(response.status_code, 403)


class WebhookSignatureEnforcementTests(unittest.TestCase):
    """AC3 / AC4 / AC5 – POST /webhook HMAC, timestamp, replay, and rejection isolation."""

    def setUp(self):
        from app.decorators import security
        from app.views import webhook_blueprint

        self._env_patch = patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta"}, clear=True)
        self._env_patch.start()

        security.clear_signature_replay_cache()
        self.app = Flask(__name__)
        self.app.config.update(
            {
                "WHATSAPP_PROVIDER": "meta",
                "APP_SECRET": "test-secret",
                "SIGNATURE_MAX_SKEW_SECONDS": 300,
                "SIGNATURE_REPLAY_WINDOW_SECONDS": 300,
                "IDEMPOTENCY_WINDOW_SECONDS": 300,
                "VERIFY_TOKEN": "verify-token",
            }
        )
        self.app.register_blueprint(webhook_blueprint)
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def _signature(self, payload: str) -> str:
        digest = hmac.new(
            b"test-secret", msg=payload.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"

    def test_post_webhook_requires_valid_hmac_signature(self):
        """AC3: POST without valid HMAC-SHA256 header is rejected with 403."""
        response = self.client.post(
            "/webhook",
            data="{}",
            headers={"X-Hub-Signature-256": "sha256=badhash"},
        )
        self.assertEqual(response.status_code, 403)

    def test_post_webhook_rejects_missing_signature_header(self):
        """AC3: POST with no X-Hub-Signature-256 header is rejected with 403."""
        response = self.client.post("/webhook", data="{}")
        self.assertEqual(response.status_code, 403)

    def test_post_webhook_accepts_valid_signature(self):
        """AC3: POST with correct HMAC is admitted to handler."""
        payload = '{"object":"whatsapp_business_account","entry":[]}'
        with patch("app.views.process_whatsapp_message"), patch(
            "app.utils.whatsapp_utils.is_valid_whatsapp_message", return_value=False
        ):
            response = self.client.post(
                "/webhook",
                data=payload,
                content_type="application/json",
                headers={"X-Hub-Signature-256": self._signature(payload)},
            )
        # 404 means it passed signature check and reached the handler
        self.assertIn(response.status_code, (200, 404))

    def test_post_webhook_enforces_timestamp_skew(self):
        """AC4: stale timestamp header → 403 before business logic."""
        payload = "{}"
        with patch("app.decorators.security.time.time", return_value=2000):
            response = self.client.post(
                "/webhook",
                data=payload,
                headers={
                    "X-Hub-Signature-256": self._signature(payload),
                    "X-Hub-Signature-Timestamp": "1000",  # 1000 s old
                },
            )
        self.assertEqual(response.status_code, 403)

    def test_post_webhook_blocks_replay(self):
        """AC4: re-used signature+timestamp → 403 on second request."""
        payload = "{}"
        sig = self._signature(payload)
        headers = {
            "X-Hub-Signature-256": sig,
            "X-Hub-Signature-Timestamp": "1700000000",
        }
        with patch("app.decorators.security.time.time", return_value=1700000010), \
             patch("app.utils.whatsapp_utils.is_valid_whatsapp_message", return_value=False):
            first = self.client.post("/webhook", data=payload, content_type="application/json", headers=headers)
            second = self.client.post("/webhook", data=payload, content_type="application/json", headers=headers)

        self.assertIn(first.status_code, (200, 404))
        self.assertEqual(second.status_code, 403)

    def test_rejection_does_not_invoke_downstream_processing(self):
        """AC5: invalid signature must not reach process_whatsapp_message."""
        with patch("app.views.process_whatsapp_message") as mock_process:
            self.client.post(
                "/webhook",
                data="{}",
                headers={"X-Hub-Signature-256": "sha256=garbage"},
            )
        mock_process.assert_not_called()

    def test_post_webhook_rejects_malformed_signature_prefix(self):
        """AC3: header present but without sha256= prefix is rejected with 403."""
        response = self.client.post(
            "/webhook",
            data="{}",
            headers={"X-Hub-Signature-256": "hmac-sha256=abc123"},
        )
        self.assertEqual(response.status_code, 403)

    def test_rejection_response_includes_correlation_id_and_reason(self):
        """AC5: rejection JSON must contain correlation_id and a stable reason code."""
        response = self.client.post(
            "/webhook",
            data="{}",
            headers={"X-Hub-Signature-256": "sha256=badhash"},
        )
        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertIn("correlation_id", payload)
        self.assertIn("reason", payload)
        self.assertIsInstance(payload["correlation_id"], str)
        self.assertGreater(len(payload["correlation_id"]), 0)

    def test_rejection_payload_does_not_leak_app_secret(self):
        """AC2/AC5: APP_SECRET value must not appear in rejection response body."""
        response = self.client.post(
            "/webhook",
            data="{}",
            headers={"X-Hub-Signature-256": "sha256=badhash"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"test-secret", response.data)

    def test_get_rejection_response_includes_correlation_id_and_reason(self):
        """AC2/AC5: GET 403 rejection JSON must contain correlation_id and reason."""
        response = self.client.get(
            "/webhook",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertIn("correlation_id", payload)
        self.assertIn("reason", payload)
        self.assertIsInstance(payload["correlation_id"], str)
        self.assertGreater(len(payload["correlation_id"]), 0)


class EvolutionWebhookTests(unittest.TestCase):
    def setUp(self):
        from app.views import webhook_blueprint

        self._env_patch = patch.dict(os.environ, {
            "WHATSAPP_PROVIDER": "evolution",
            "EVOLUTION_API_URL": "https://evolution.example.com",
            "EVOLUTION_API_KEY": "evo-key",
            "EVOLUTION_INSTANCE_NAME": "bot-instance",
        }, clear=True)
        self._env_patch.start()

        self.app = Flask(__name__)
        self.app.config.update(
            {
                "WHATSAPP_PROVIDER": "evolution",
                "EVOLUTION_API_URL": "https://evolution.example.com",
                "EVOLUTION_API_KEY": "evo-key",
                "EVOLUTION_INSTANCE_NAME": "bot-instance",
                "OPENAI_API_KEY": "openai-key",
            }
        )
        self.app.register_blueprint(webhook_blueprint)
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def _payload(self):
        return {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "id": "evo-msg-1",
                    "remoteJid": "15551234567@s.whatsapp.net",
                    "fromMe": False,
                },
                "pushName": "Evolution User",
                "message": {"conversation": "hello from evolution"},
            },
        }

    def test_get_webhook_returns_ready_response_for_evolution(self):
        response = self.client.get("/webhook")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["provider"], "evolution")

    def test_post_webhook_accepts_evolution_payload_without_meta_signature(self):
        with patch(
            "app.views.process_whatsapp_message",
            return_value={
                "from": "15551234567",
                "message_id": "evo-msg-1",
                "agent": "Ops",
                "input_text": "hello from evolution",
                "reply_text": "reply",
                "status": "sent",
                "error": None,
            },
        ) as mock_process:
            response = self.client.post(
                "/webhook",
                json=self._payload(),
            )

        self.assertEqual(response.status_code, 200)
        mock_process.assert_called_once()

    def test_post_webhook_rejects_invalid_evolution_secret(self):
        self.app.config["EVOLUTION_WEBHOOK_SECRET"] = "expected-secret"

        response = self.client.post(
            "/webhook",
            json=self._payload(),
            headers={"apikey": "wrong-secret"},
        )

        self.assertEqual(response.status_code, 403)

    def test_post_webhook_blocked_when_startup_config_invalid(self):
        self.app.extensions["config_validation_errors"] = [
            "Missing required configuration: OPENAI_API_KEY"
        ]

        with patch("app.views.process_whatsapp_message") as mock_process:
            response = self.client.post(
                "/webhook",
                json=self._payload(),
            )

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["reason"], "config_invalid")
        self.assertNotIn("details", payload)
        mock_process.assert_not_called()


# ---------------------------------------------------------------------------
# Story 7.10 — is_config_value_set boundary contract tests
# ---------------------------------------------------------------------------

class IsConfigValueSetBoundaryTests(unittest.TestCase):
    """
    Contract tests for app.config.is_config_value_set().
    Asserts explicit boundary behaviour for None, empty, whitespace, and
    edge-case falsy Python values that must NOT be confused with absent config.
    """

    def _check(self, value, expected: bool, msg: str):
        from app.config import is_config_value_set

        result = is_config_value_set(value)
        self.assertEqual(result, expected, msg)

    def test_none_returns_false(self):
        self._check(None, False, "None should be treated as absent")

    def test_empty_string_returns_false(self):
        self._check("", False, "Empty string should be treated as absent")

    def test_whitespace_only_string_returns_false(self):
        self._check("   ", False, "Whitespace-only string should be treated as absent")

    def test_tab_only_string_returns_false(self):
        self._check("\t", False, "Tab-only string should be treated as absent")

    def test_newline_only_string_returns_false(self):
        self._check("\n", False, "Newline-only string should be treated as absent")

    def test_zero_string_returns_true(self):
        """'0' is a valid config value, not absent."""
        self._check("0", True, "'0' string should be treated as present")

    def test_false_string_returns_true(self):
        """'false' is a valid (non-empty) config value."""
        self._check("false", True, "'false' string should be treated as present")

    def test_non_empty_string_returns_true(self):
        self._check("some-key", True, "Non-empty string should be treated as present")

    def test_integer_zero_returns_true(self):
        """Integer 0 is a valid non-None config value; only None and blank str are absent."""
        self._check(0, True, "Integer 0 should be treated as present (not None)")

    def test_boolean_false_returns_true(self):
        """False boolean is a valid non-None config value."""
        self._check(False, True, "Boolean False should be treated as present (not None)")

    def test_non_string_truthy_value_returns_true(self):
        self._check(42, True, "Non-zero int should be treated as present")

    def test_list_value_returns_true(self):
        self._check([], True, "Empty list is not None so should be treated as present")


if __name__ == "__main__":
    unittest.main()
