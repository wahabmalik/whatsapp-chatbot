"""
Endpoint Contract Tests — Epic 4 Carry-Forward Action #1

Verifies that all documented operational endpoints exist and are reachable
in the Flask route map. CI should fail on any mismatch.

Documented endpoints (from operations_runbook.md and epic-4-retro carry-forward):
  GET /health
  GET /metrics
  GET /api/health
  GET /api/metrics
  GET /api/logs
  GET /operator/metrics

For each endpoint this suite checks:
  1. The URL is registered in the Flask URL map (route existence)
  2. The route accepts GET requests
  3. The route returns a non-5xx response under a valid operator session
     (some routes require operator role; unauthenticated GET returns 302/403, not 500)
"""
import os
import unittest
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
}

# Documented operational endpoints that must always exist.
DOCUMENTED_ENDPOINTS = [
    "/health",
    "/metrics",
    "/api/health",
    "/api/metrics",
    "/api/logs",
    "/api/thread-inspector",
    "/operator/metrics",
]


def _make_app():
    with patch.dict(os.environ, _BASE_ENV, clear=False):
        from app import create_app
        return create_app()


class EndpointRouteExistenceTests(unittest.TestCase):
    """All documented endpoints are registered in the Flask URL map."""

    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        cls._env.start()
        cls.app = _make_app()
        # Build a set of all registered URL rules
        cls.registered_urls = {rule.rule for rule in cls.app.url_map.iter_rules()}

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()

    def _assert_endpoint_registered(self, path: str):
        self.assertIn(
            path,
            self.registered_urls,
            f"Documented endpoint '{path}' is not registered in Flask URL map. "
            f"Update the route or the documentation to keep them in sync.",
        )

    def test_health_endpoint_registered(self):
        """/health is in the URL map."""
        self._assert_endpoint_registered("/health")

    def test_metrics_endpoint_registered(self):
        """/metrics is in the URL map."""
        self._assert_endpoint_registered("/metrics")

    def test_api_health_endpoint_registered(self):
        """/api/health is in the URL map."""
        self._assert_endpoint_registered("/api/health")

    def test_api_metrics_endpoint_registered(self):
        """/api/metrics is in the URL map."""
        self._assert_endpoint_registered("/api/metrics")

    def test_api_logs_endpoint_registered(self):
        """/api/logs is in the URL map."""
        self._assert_endpoint_registered("/api/logs")

    def test_api_thread_inspector_endpoint_registered(self):
        """/api/thread-inspector is in the URL map."""
        self._assert_endpoint_registered("/api/thread-inspector")

    def test_operator_metrics_endpoint_registered(self):
        """/operator/metrics is in the URL map."""
        self._assert_endpoint_registered("/operator/metrics")


class EndpointGetMethodTests(unittest.TestCase):
    """All documented endpoints accept GET requests."""

    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        cls._env.start()
        cls.app = _make_app()
        cls.rules_by_path = {
            rule.rule: rule for rule in cls.app.url_map.iter_rules()
        }

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()

    def _assert_accepts_get(self, path: str):
        rule = self.rules_by_path.get(path)
        self.assertIsNotNone(rule, f"Route '{path}' not found in URL map.")
        self.assertIn(
            "GET",
            rule.methods or set(),
            f"Route '{path}' does not accept GET. Methods: {rule.methods}",
        )

    def test_health_accepts_get(self):
        self._assert_accepts_get("/health")

    def test_metrics_accepts_get(self):
        self._assert_accepts_get("/metrics")

    def test_api_health_accepts_get(self):
        self._assert_accepts_get("/api/health")

    def test_api_metrics_accepts_get(self):
        self._assert_accepts_get("/api/metrics")

    def test_api_logs_accepts_get(self):
        self._assert_accepts_get("/api/logs")

    def test_api_thread_inspector_accepts_get(self):
        self._assert_accepts_get("/api/thread-inspector")

    def test_operator_metrics_accepts_get(self):
        self._assert_accepts_get("/operator/metrics")


class EndpointReachabilityTests(unittest.TestCase):
    """All documented endpoints return non-5xx responses."""

    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        cls._env.start()
        cls.app = _make_app()
        cls.app.config["SECRET_KEY"] = "test-secret-endpoint"
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        # Set operator session for routes that require it
        with cls.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()

    def _assert_not_server_error(self, path: str):
        response = self.client.get(path)
        self.assertLess(
            response.status_code,
            500,
            f"Endpoint '{path}' returned server error {response.status_code}. "
            f"Route handler is broken.",
        )

    def test_health_does_not_return_5xx(self):
        self._assert_not_server_error("/health")

    def test_metrics_does_not_return_5xx(self):
        self._assert_not_server_error("/metrics")

    def test_api_health_does_not_return_5xx(self):
        self._assert_not_server_error("/api/health")

    def test_api_metrics_does_not_return_5xx(self):
        self._assert_not_server_error("/api/metrics")

    def test_api_logs_does_not_return_5xx(self):
        self._assert_not_server_error("/api/logs")

    def test_api_thread_inspector_does_not_return_5xx(self):
        self._assert_not_server_error("/api/thread-inspector")

    def test_operator_metrics_does_not_return_5xx(self):
        self._assert_not_server_error("/operator/metrics")


class EndpointCompletenessGuardTest(unittest.TestCase):
    """
    Catch-all: ensures DOCUMENTED_ENDPOINTS list matches registered routes.
    If a route is renamed or removed without updating this file, this test fails
    to prompt updating the documentation catalog.
    """

    def test_all_documented_endpoints_are_registered(self):
        """Every entry in DOCUMENTED_ENDPOINTS exists in the live URL map."""
        with patch.dict(os.environ, _BASE_ENV, clear=False):
            from app import create_app
            app = create_app()

        registered = {rule.rule for rule in app.url_map.iter_rules()}
        missing = [ep for ep in DOCUMENTED_ENDPOINTS if ep not in registered]
        self.assertEqual(
            missing,
            [],
            f"The following documented endpoints are not registered: {missing}. "
            f"Either add the route or remove it from DOCUMENTED_ENDPOINTS.",
        )


if __name__ == "__main__":
    unittest.main()
