---
story_id: "CF4.1"
story_key: "cf4-1-docs-runtime-endpoint-contract-test"
status: "ready-for-dev"
epic: "carry-forward-epic-4"
carry_forward_from: "epic-4-retro-2026-05-01"
owner: "Developer (Amelia)"
due: "2026-05-06"
created: "2026-05-02"
depends_on:
  - "4.1 (automated-quality-and-launch-gates)"
  - "4.2 (setup-guide-runbook-and-monitoring-operations)"
---

# CF4.1: Docs-Runtime Endpoint Contract Test

## Origin

**Source:** Epic 4 Retrospective carry-forward action #1 (see `_bmad-output/implementation-artifacts/epic-4-retro-2026-05-01.md`, Action Items table, row 1).

**Root cause addressed:** During Epic 4, contract drift occurred between documented operational endpoints and implemented routes. The `/operator/metrics` route was documented but not wired until a mid-sprint review caught it. Drift detection was reactive rather than CI-gated. This story codifies the check so the same regression cannot reach main undetected.

---

## User Story

As a release owner,
I want a CI-gated test that verifies all documented operational endpoints exist and are reachable in the Flask route map,
so that any future docs-runtime contract drift is caught automatically before merge rather than discovered during operator review.

---

## Acceptance Criteria

1. **All six documented endpoints are covered:**  `/health`, `/metrics`, `/api/health`, `/api/metrics`, `/api/logs`, `/operator/metrics`.
2. **Route existence is verified:** Each endpoint resolves to a live route handler under the registered blueprints (i.e., Flask does not return 404 or 405 for GET requests).
3. **Auth and format expectations are verified per endpoint:**
   - Unauthenticated requests to `/health`, `/metrics`, `/api/health`, `/api/metrics`, `/api/logs` return HTTP 200 with `Content-Type: application/json`.
   - Unauthenticated requests to `/operator/metrics` return HTTP 302 (redirect to `/operator/access`) — confirming the route exists and the operator guard is active.
   - Authenticated operator requests to `/operator/metrics` return HTTP 200.
4. **Route handler presence is confirmed:** Test asserts that each endpoint maps to a named view function (via Flask's `url_map`), not just that it returns a non-404.
5. **CI fails on mismatch:** Any 404, 405, unexpected status code, or missing Content-Type causes the test to fail with a clear assertion message identifying the endpoint.
6. **Test is runnable with `pytest tests/` without additional setup** beyond the project's standard test environment variables.

---

## Context and Constraints

### Route Map (as of 2026-05-02)

Both blueprints are registered without a URL prefix in `app/__init__.py`:

```python
app.register_blueprint(webhook_blueprint)   # views.py
app.register_blueprint(dashboard_blueprint) # views_dashboard.py
```

| Endpoint | Blueprint | Handler | Auth Guard | Expected Response |
|---|---|---|---|---|
| `GET /health` | `webhook_blueprint` | `health()` | None | 200 JSON |
| `GET /metrics` | `webhook_blueprint` | `metrics()` | None | 200 JSON |
| `GET /api/health` | `dashboard_blueprint` | `health_api()` | None | 200 JSON |
| `GET /api/metrics` | `dashboard_blueprint` | `metrics_api()` | None | 200 JSON |
| `GET /api/logs` | `dashboard_blueprint` | `logs_api()` | None | 200 JSON (array) |
| `GET /operator/metrics` | `dashboard_blueprint` | `metrics_page()` | `_require_operator_access()` — redirects if session role ≠ `operator` | 302 unauthenticated; 200 HTML authenticated |

### Why `/operator/metrics` returns HTML, not JSON

`/operator/metrics` renders `metrics.html` for the operator dashboard view. The contract test must treat this correctly: the endpoint's contract is that it renders (200 + HTML) when the operator role is set, and redirects to `/operator/access` (302) when it is not. Asserting on Content-Type `text/html` when authenticated is the correct check, not `application/json`.

### Operator Role Session Mechanism

The dashboard uses a session key `dashboard_role`. Setting it to `"operator"` grants access to guarded routes. In the test client, this can be set via `client.session_transaction()`:

```python
with client.session_transaction() as sess:
    sess["dashboard_role"] = "operator"
```

### Standard Test Environment Variables

Tests use `patch.dict(os.environ, ..., clear=True)` with a minimal required-env dict (see pattern in `tests/test_story_1_3.py`). The same `FULL_REQUIRED_ENV` dict used across the test suite is appropriate here.

---

## Tasks / Subtasks

- [ ] **Task 1: Create `tests/test_endpoint_contract.py`** (AC: 1, 2, 3, 4, 5, 6)
  - [ ] Define `DOCUMENTED_ENDPOINTS` constant listing all six endpoints with expected status code, expected Content-Type prefix, and whether operator auth is required.
  - [ ] Write `EndpointContractTests` class using `unittest.TestCase`, with `setUp` creating the Flask app via `create_app()` under `patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)`.
  - [ ] Write `test_unauthenticated_json_endpoints` that iterates the five no-auth JSON endpoints and asserts: status 200, Content-Type contains `application/json`.
  - [ ] Write `test_operator_metrics_unauthenticated_redirects` that asserts `/operator/metrics` GET without operator role returns 302 and `Location` header contains `/operator/access`.
  - [ ] Write `test_operator_metrics_authenticated_returns_200` that sets operator session role, makes GET `/operator/metrics`, asserts 200 with Content-Type `text/html`.
  - [ ] Write `test_route_handler_presence` that introspects `app.url_map` and asserts each of the six endpoints resolves to a named endpoint (not None/404), providing the endpoint path in the failure message.

- [ ] **Task 2: Verify test runs cleanly under `pytest`** (AC: 6)
  - [ ] Run `pytest tests/test_endpoint_contract.py -v` and confirm all tests pass.
  - [ ] Confirm no import errors or fixture bleed from other test files.

- [ ] **Task 3: Validate CI-fail behavior** (AC: 5)
  - [ ] Temporarily rename one route handler (e.g., comment out one `@blueprint.route(...)` decorator) and confirm the contract test fails with a clear message before reverting.

- [ ] **Task 4: Update `sprint-status.yaml`** (AC implied by project hygiene)
  - [ ] Add `cf4-1-docs-runtime-endpoint-contract-test` entry under `development_status` with status `done` upon completion.

---

## Test Plan

### Test File
`tests/test_endpoint_contract.py`

### Test Cases

| Test | Inputs | Expected Result |
|---|---|---|
| `test_unauthenticated_json_endpoints` | GET `/health`, `/metrics`, `/api/health`, `/api/metrics`, `/api/logs` | 200 OK, `Content-Type: application/json` for each |
| `test_operator_metrics_unauthenticated_redirects` | GET `/operator/metrics`, no session role | 302, Location contains `/operator/access` |
| `test_operator_metrics_authenticated_returns_200` | GET `/operator/metrics`, session role = `operator` | 200, Content-Type `text/html` |
| `test_route_handler_presence` | Introspect `app.url_map` for all 6 endpoints | Each resolves to a named Flask endpoint string |

### Failure Mode Validation

To confirm CI-fail behavior (Task 3 above), comment out one route decorator:

```python
# @webhook_blueprint.route("/health", methods=["GET"])
```

Expected result: `test_unauthenticated_json_endpoints` fails with:

```
AssertionError: /health returned 404, expected 200
```

Revert immediately after validation.

### Run Command
```powershell
pytest tests/test_endpoint_contract.py -v
```

---

## Implementation Notes

### Recommended Test Structure

```python
"""Contract test: all documented operational endpoints exist and are reachable."""

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
    ("/health",          200, "application/json", False),
    ("/metrics",         200, "application/json", False),
    ("/api/health",      200, "application/json", False),
    ("/api/metrics",     200, "application/json", False),
    ("/api/logs",        200, "application/json", False),
    ("/operator/metrics", 200, "text/html",       True),
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
        json_endpoints = [
            (path, status, ct)
            for path, status, ct, auth in DOCUMENTED_ENDPOINTS
            if not auth
        ]
        for path, expected_status, expected_ct in json_endpoints:
            with self.subTest(endpoint=path):
                resp = self.client.get(path)
                self.assertEqual(
                    resp.status_code, expected_status,
                    f"{path} returned {resp.status_code}, expected {expected_status}"
                )
                self.assertIn(
                    expected_ct, resp.content_type,
                    f"{path} Content-Type was '{resp.content_type}', expected '{expected_ct}'"
                )

    def test_operator_metrics_unauthenticated_redirects(self):
        resp = self.client.get("/operator/metrics")
        self.assertEqual(
            resp.status_code, 302,
            f"/operator/metrics returned {resp.status_code} for unauthenticated request, expected 302"
        )
        location = resp.headers.get("Location", "")
        self.assertIn(
            "/operator/access", location,
            f"/operator/metrics redirect Location '{location}' does not contain '/operator/access'"
        )

    def test_operator_metrics_authenticated_returns_200(self):
        self._set_operator_session()
        resp = self.client.get("/operator/metrics")
        self.assertEqual(
            resp.status_code, 200,
            f"/operator/metrics returned {resp.status_code} for operator session, expected 200"
        )
        self.assertIn(
            "text/html", resp.content_type,
            f"/operator/metrics Content-Type was '{resp.content_type}', expected 'text/html'"
        )

    def test_route_handler_presence(self):
        """Verify each documented endpoint resolves to a named handler in the url_map."""
        with self.app.test_request_context():
            from flask import url_for
            for path, _, _, _ in DOCUMENTED_ENDPOINTS:
                # Attempt to match the rule — a 404 means the route is not registered.
                adapter = self.app.url_map.bind("localhost")
                try:
                    endpoint, _ = adapter.match(path, method="GET")
                    self.assertIsNotNone(
                        endpoint,
                        f"Route handler for {path} resolved to None in url_map"
                    )
                except Exception as exc:  # werkzeug.exceptions.NotFound / MethodNotAllowed
                    self.fail(f"Route {path} is not registered in url_map: {exc}")
```

### Notes on `test_route_handler_presence`

This test introspects `app.url_map` directly using Werkzeug's `MapAdapter.match()`. This is the strongest possible check: it does not go through the WSGI stack and will catch cases where a route was removed from the blueprint but docs were not updated (or vice versa). It complements the HTTP-level tests which catch auth regressions.

### Why `subTest` is used

`subTest` ensures all six endpoints are checked in a single test run rather than stopping at the first failure. The failure message includes the endpoint path, which is the minimum diagnostic needed for a CI operator to identify the drift without reading the full traceback.

---

## Risks and Follow-Ups

| Risk | Likelihood | Mitigation |
|---|---|---|
| A future route gains a URL prefix in blueprint registration | Medium | `test_route_handler_presence` will catch this immediately since paths change |
| A new documented endpoint is added to the runbook but not added to `DOCUMENTED_ENDPOINTS` | Medium | Add a review note: any runbook change to monitoring endpoints must include a corresponding update to this test file |
| `/operator/metrics` redirect target changes (e.g., new access gate) | Low | `test_operator_metrics_unauthenticated_redirects` will fail with clear message |
| Test environment setup variance (missing required env key causes `create_app` to behave differently) | Low | `FULL_REQUIRED_ENV` matches the project-standard pattern used in `test_story_1_3.py` and others |

**Follow-up (not blocking this story):** Add `DOCUMENTED_ENDPOINTS` as a shared fixture or constant in a `tests/conftest.py` if additional endpoint-contract tests are added in future sprints. Do not do this now; YAGNI applies.

---

## Definition of Done

- [ ] `tests/test_endpoint_contract.py` exists and all test cases pass under `pytest tests/test_endpoint_contract.py -v`.
- [ ] CI-fail behavior validated by temporarily removing one route and confirming test failure, then reverting.
- [ ] `sprint-status.yaml` updated to reflect `cf4-1-docs-runtime-endpoint-contract-test: done`.
- [ ] No existing tests broken (run `pytest tests/ -q` and confirm no regressions).
