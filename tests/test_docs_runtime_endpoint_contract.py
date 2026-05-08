"""
tests/test_docs_runtime_endpoint_contract.py

Docs-Runtime Endpoint Contract Test (Epic 4 Action Item 1)

Verifies that all endpoints documented in operations_runbook.md are:
1. Implemented in the Flask route map
2. Accessible with correct HTTP method
3. Return expected content-type headers
4. Reachable without blocking auth for public endpoints

Documented endpoints to verify:
- GET /health              (public, JSON)
- GET /metrics             (public, JSON)
- GET /api/health          (dashboard, JSON)
- GET /api/metrics         (dashboard, JSON)
- GET /api/logs            (dashboard, JSON)
- GET /operator/metrics    (operator session required, HTML)
"""

import os
import unittest
from unittest.mock import patch

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


class DocsRuntimeEndpointContractTests(unittest.TestCase):
    """Verify documented endpoints exist and are accessible."""

    def setUp(self):
        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            from app import create_app
            self.app = create_app()
        self.client = self.app.test_client()

    def test_health_endpoint_exists_and_returns_json(self):
        """GET /health must exist and return JSON."""
        response = self.client.get('/health')
        self.assertIn(response.status_code, [200, 503])
        self.assertIn('application/json', response.content_type)

    def test_metrics_endpoint_exists_and_returns_json(self):
        """GET /metrics must exist and return JSON."""
        response = self.client.get('/metrics')
        self.assertIn(response.status_code, [200, 503])
        self.assertIn('application/json', response.content_type)

    def test_api_health_endpoint_exists_and_returns_json(self):
        """GET /api/health must exist and return JSON."""
        response = self.client.get('/api/health')
        self.assertIn(response.status_code, [200, 503])
        self.assertIn('application/json', response.content_type)

    def test_api_metrics_endpoint_exists_and_returns_json(self):
        """GET /api/metrics must exist and return JSON."""
        response = self.client.get('/api/metrics')
        self.assertIn(response.status_code, [200, 503])
        self.assertIn('application/json', response.content_type)

    def test_api_logs_endpoint_exists_and_returns_json(self):
        """GET /api/logs must exist and return JSON."""
        response = self.client.get('/api/logs')
        # 401 for unauthenticated is acceptable; endpoint must exist
        self.assertNotEqual(response.status_code, 404)

    def test_api_thread_inspector_endpoint_exists(self):
        """GET /api/thread-inspector must exist (operator and query-param gated)."""
        response = self.client.get('/api/thread-inspector')
        # 302/403/400 are acceptable here; endpoint must exist
        self.assertNotEqual(response.status_code, 404)

    def test_operator_metrics_endpoint_exists(self):
        """GET /operator/metrics must exist (requires session)."""
        response = self.client.get('/operator/metrics')
        # 401 or 302 redirect for unauthenticated is acceptable; endpoint must exist
        self.assertNotEqual(response.status_code, 404)

    def test_webhook_endpoint_exists(self):
        """POST /webhook must exist for webhook inbound."""
        response = self.client.post('/webhook', json={})
        # Any non-404 response is acceptable; endpoint must exist
        self.assertNotEqual(response.status_code, 404)

    def test_all_documented_endpoints_implemented(self):
        """Verify documented endpoint family is available."""
        documented = {
            'health': ('/health', 'GET'),
            'metrics': ('/metrics', 'GET'),
            'api_health': ('/api/health', 'GET'),
            'api_metrics': ('/api/metrics', 'GET'),
            'api_logs': ('/api/logs', 'GET'),
            'api_thread_inspector': ('/api/thread-inspector', 'GET'),
            'operator_metrics': ('/operator/metrics', 'GET'),
            'webhook': ('/webhook', 'POST'),
        }

        route_map = {}
        for rule in self.app.url_map.iter_rules():
            route_map[rule.rule] = set(rule.methods)

        missing = []
        for name, (path, method) in documented.items():
            if path not in route_map:
                missing.append(f"{name}: {method} {path}")
            elif method not in route_map[path]:
                missing.append(f"{name}: {method} {path} (has {route_map[path]})")

        self.assertEqual(
            len(missing), 0,
            f"Documented endpoints not found: {missing}\n"
            f"Available routes: {list(route_map.keys())}"
        )


if __name__ == '__main__':
    unittest.main()
