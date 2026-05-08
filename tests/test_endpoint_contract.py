"""Contract tests for documented runtime endpoints (CF4.1)."""

from __future__ import annotations

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

# (endpoint_path, expected_status, expected_content_type_prefix, requires_operator_auth)
DOCUMENTED_ENDPOINTS = [
    ("/health", 200, "application/json", False),
    ("/metrics", 200, "application/json", False),
    ("/api/health", 200, "application/json", False),
    ("/api/metrics", 200, "application/json", False),
    ("/api/logs", 200, "application/json", False),
    ("/operator/metrics", 200, "text/html", True),
]


class EndpointContractTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()
        from app import create_app

        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self._env_patch.stop()

    def _set_operator_session(self):
        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def test_unauthenticated_json_endpoints(self):
        for path, expected_status, expected_ct, requires_auth in DOCUMENTED_ENDPOINTS:
            if requires_auth:
                continue
            with self.subTest(endpoint=path):
                response = self.client.get(path)
                self.assertEqual(
                    response.status_code,
                    expected_status,
                    f"{path} returned {response.status_code}, expected {expected_status}",
                )
                self.assertIn(
                    expected_ct,
                    response.content_type,
                    f"{path} content_type '{response.content_type}' missing '{expected_ct}'",
                )

    def test_operator_metrics_unauthenticated_redirects(self):
        response = self.client.get("/operator/metrics", follow_redirects=False)
        self.assertEqual(
            response.status_code,
            302,
            f"/operator/metrics returned {response.status_code}, expected 302",
        )
        location = response.headers.get("Location", "")
        self.assertIn(
            "/operator/access",
            location,
            f"/operator/metrics redirect location '{location}' missing '/operator/access'",
        )

    def test_operator_metrics_authenticated_returns_html(self):
        self._set_operator_session()
        response = self.client.get("/operator/metrics")
        self.assertEqual(
            response.status_code,
            200,
            f"/operator/metrics returned {response.status_code}, expected 200",
        )
        self.assertIn(
            "text/html",
            response.content_type,
            f"/operator/metrics content_type '{response.content_type}' missing 'text/html'",
        )

    def test_route_handler_presence(self):
        adapter = self.app.url_map.bind("localhost")
        for path, _status, _ct, _auth in DOCUMENTED_ENDPOINTS:
            with self.subTest(endpoint=path):
                try:
                    endpoint, _args = adapter.match(path, method="GET")
                except Exception as exc:  # pragma: no cover
                    self.fail(f"Route {path} is not registered in url_map: {exc}")

                self.assertIsInstance(endpoint, str, f"Route {path} resolved to non-string endpoint")
                self.assertTrue(endpoint, f"Route {path} resolved to an empty endpoint")


if __name__ == "__main__":
    unittest.main()
