"""Explicit traceability checks for stories previously marked partial.

This module avoids runtime provider paths and focuses on deterministic
evidence checks for 2.2, 3.1, and 3.2 acceptance surfaces.
"""

from __future__ import annotations

import inspect
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


class Story22TraceabilityProofTests(unittest.TestCase):
    """Story 2.2 traceability: explicit contract test suite presence."""

    def test_release_openai_contract_suite_contains_key_contract_cases(self):
        import tests.test_release_gates as release_gates

        suite = release_gates.ReleaseOpenAIContractTests
        method_names = {
            name
            for name, member in inspect.getmembers(suite, predicate=inspect.isfunction)
            if name.startswith("test_")
        }

        expected = {
            "test_generate_reply_result_success_contract_shape",
            "test_generate_reply_result_timeout_is_controlled_state",
            "test_generate_reply_result_auth_is_controlled_state",
            "test_generate_reply_result_rate_limit_is_controlled_state",
            "test_generate_reply_result_records_metrics",
        }
        self.assertTrue(expected.issubset(method_names))


class Story31ControlPlaneTests(unittest.TestCase):
    """Story 3.1 traceability: runtime control-plane save and guards."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
            sess["_csrf_token"] = "story-3-1-token"

    def tearDown(self):
        self._env_patch.stop()

    def test_agents_post_saves_selected_code_with_valid_csrf(self):
        with patch(
            "app.views_dashboard.list_bmad_agents",
            return_value=[{"code": "bmad-agent-dev", "name": "Amelia"}],
        ), patch("app.views_dashboard.set_selected_agent_code") as mock_set:
            response = self.client.post(
                "/agents",
                data={"agent_code": "bmad-agent-dev"},
                headers={"X-CSRFToken": "story-3-1-token"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        mock_set.assert_called_once_with("bmad-agent-dev")


class Story32SetupWorkflowTests(unittest.TestCase):
    """Story 3.2 traceability: setup progression and operator redirect."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
            sess["_csrf_token"] = "story-3-2-token"

    def tearDown(self):
        self._env_patch.stop()

    def test_setup_verify_blocks_when_required_keys_missing(self):
        self.app.config["ACCESS_TOKEN"] = ""

        response = self.client.post(
            "/setup/verify",
            headers={"X-CSRFToken": "story-3-2-token"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("ACCESS_TOKEN", payload.get("missing", []))

    def test_setup_complete_cta_routes_to_operator_dashboard(self):
        response = self.client.get("/setup")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/operator"', response.data)


if __name__ == "__main__":
    unittest.main()
