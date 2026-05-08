"""
Test setup status and configuration validation features for operators.

Ensures operators can:
1. Check setup status via API
2. See validation errors clearly
3. Have webhooks blocked until setup is complete
"""

import json
import os
import unittest
from unittest.mock import patch

from flask import Flask


MINIMAL_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
}


class SetupStatusAPITests(unittest.TestCase):
    """Test the /api/setup/status endpoint for operators."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, MINIMAL_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_setup_status_requires_operator_access(self):
        """Setup status endpoint should require operator role."""
        from app import create_app

        app = create_app()
        client = app.test_client()

        with client.session_transaction() as sess:
            sess.clear()

        response = client.get("/api/setup/status")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/operator/access", response.location)

    def test_setup_status_shows_complete_when_all_keys_present(self):
        """Setup status should show complete when all required keys are set."""
        from app import create_app

        app = create_app()
        client = app.test_client()

        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

        response = client.get("/api/setup/status")
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertTrue(data["ok"])
        self.assertTrue(data["setup_complete"])
        self.assertEqual(len(data["validation_errors"]), 0)

    def test_setup_status_shows_missing_keys(self):
        """Setup status should list missing required keys."""
        with patch.dict(os.environ, {"PHONE_NUMBER_ID": ""}, clear=False):
            from app import create_app

            app = create_app()
            client = app.test_client()

            with client.session_transaction() as sess:
                sess["dashboard_role"] = "operator"

            response = client.get("/api/setup/status")
            self.assertEqual(response.status_code, 200)

            data = json.loads(response.data)
            self.assertTrue(data["ok"])
            self.assertFalse(data["setup_complete"])
            self.assertIn("PHONE_NUMBER_ID", data["missing_keys"])
            self.assertGreater(len(data["config_readiness"]), 0)

    def test_setup_status_shows_validation_errors(self):
        """Setup status should show validation errors."""
        with patch.dict(os.environ, {"VERSION": "invalid"}, clear=False):
            from app import create_app

            app = create_app()
            client = app.test_client()

            with client.session_transaction() as sess:
                sess["dashboard_role"] = "operator"

            response = client.get("/api/setup/status")
            self.assertEqual(response.status_code, 200)

            data = json.loads(response.data)
            self.assertTrue(data["ok"])
            self.assertFalse(data["setup_complete"])
            self.assertGreater(len(data["validation_errors"]), 0)
            self.assertTrue(any("VERSION" in err for err in data["validation_errors"]))


class HealthEndpointSetupStatusTests(unittest.TestCase):
    """Test that health endpoint includes setup status."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, MINIMAL_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_health_endpoint_includes_setup_status(self):
        """Health endpoint should include setup status."""
        from app import create_app

        app = create_app()
        client = app.test_client()

        response = client.get("/health")
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn("setup", data)
        self.assertIn("setup_complete", data["setup"])
        self.assertIn("validation_errors", data["setup"])
        self.assertIn("required_keys", data["setup"])
        self.assertIn("missing_keys", data["setup"])

    def test_health_shows_setup_incomplete_when_keys_missing(self):
        """Health should show setup incomplete when required keys are missing."""
        with patch.dict(os.environ, {"ACCESS_TOKEN": ""}, clear=False):
            from app import create_app

            app = create_app()
            client = app.test_client()

            response = client.get("/health")
            self.assertEqual(response.status_code, 200)

            data = json.loads(response.data)
            self.assertFalse(data["setup"]["setup_complete"])
            self.assertIn("ACCESS_TOKEN", data["setup"]["missing_keys"])


class WebhookBlockingOnInvalidConfigTests(unittest.TestCase):
    """Test that webhooks are blocked when configuration is invalid."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, MINIMAL_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_webhook_blocked_when_config_invalid_returns_503(self):
        """Webhook should return 503 when configuration is invalid."""
        with patch.dict(os.environ, {"PHONE_NUMBER_ID": ""}, clear=False):
            from app import create_app

            app = create_app()
            client = app.test_client()

            # Bypass inbound signature guard so the test can assert config gating behavior.
            with patch("app.views.enforce_inbound_webhook_request", return_value=None):
                response = client.post(
                    "/webhook",
                    json={"object": "whatsapp_business_account", "entry": []},
                )

                self.assertEqual(response.status_code, 503)

    def test_webhook_blocked_response_includes_validation_errors(self):
        """Webhook 503 response should include validation errors for operator debugging."""
        with patch.dict(os.environ, {"VERSION": "invalid"}, clear=False):
            from app import create_app

            app = create_app()
            client = app.test_client()

            with patch("app.views.enforce_inbound_webhook_request", return_value=None):
                response = client.post(
                    "/webhook",
                    json={"object": "whatsapp_business_account", "entry": []},
                )

                self.assertEqual(response.status_code, 503)
                data = json.loads(response.data)
                self.assertEqual(data["reason"], "config_invalid")
                self.assertIn("validation_errors", data)
                self.assertGreater(len(data["validation_errors"]), 0)

    def test_webhook_blocked_response_has_correlation_id(self):
        """Webhook blocked response should include correlation ID for tracing."""
        with patch.dict(os.environ, {"PHONE_NUMBER_ID": ""}, clear=False):
            from app import create_app

            app = create_app()
            client = app.test_client()

            with patch("app.views.enforce_inbound_webhook_request", return_value=None):
                response = client.post(
                    "/webhook",
                    json={"object": "whatsapp_business_account", "entry": []},
                )

                self.assertEqual(response.status_code, 503)
                data = json.loads(response.data)
                self.assertIn("correlation_id", data)
                self.assertTrue(len(str(data["correlation_id"])) > 0)

    def test_webhook_succeeds_when_config_complete(self):
        """Webhook should process when configuration is complete."""
        from app import create_app
        from unittest.mock import patch as mock_patch

        app = create_app()
        client = app.test_client()

        with patch("app.views.enforce_inbound_webhook_request", return_value=None):
            # Mock webhook handling to avoid actual processing
            with mock_patch("app.utils.whatsapp_utils.process_whatsapp_message"):
                with mock_patch("app.utils.whatsapp_utils.normalize_inbound_message", return_value=None):
                    response = client.post(
                        "/webhook",
                        json={"object": "whatsapp_business_account", "entry": []},
                    )

                    # Should not be 503 (should be 404 for unsupported event or 200 if processed)
                    self.assertNotEqual(response.status_code, 503)


class SetupVerificationEndpointTests(unittest.TestCase):
    """Test POST /setup/verify endpoint behavior with new setup status."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, MINIMAL_ENV, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_setup_verify_requires_operator_access(self):
        """Setup verify endpoint should require operator role."""
        from app import create_app

        app = create_app()
        client = app.test_client()

        with client.session_transaction() as sess:
            sess.clear()

        # POST without operator role should either redirect (302) or return 403
        response = client.post(
            "/setup/verify",
            headers={"X-CSRFToken": "dummy"},
        )
        # Can be redirect or forbidden
        self.assertIn(response.status_code, [302, 403])

    def test_setup_verify_returns_missing_keys_when_incomplete(self):
        """Setup verify should return missing keys when setup incomplete."""
        with patch.dict(os.environ, {"PHONE_NUMBER_ID": ""}, clear=False):
            from app import create_app

            app = create_app()
            client = app.test_client()

            with client.session_transaction() as sess:
                sess["dashboard_role"] = "operator"
                token = "test_token"
                sess["_csrf_token"] = token

            response = client.post(
                "/setup/verify",
                headers={"X-CSRFToken": "test_token"},
            )

            self.assertEqual(response.status_code, 400)
            data = json.loads(response.data)
            self.assertFalse(data["ok"])
            self.assertIn("missing", data)
            self.assertIn("PHONE_NUMBER_ID", data["missing"])


if __name__ == "__main__":
    unittest.main()
