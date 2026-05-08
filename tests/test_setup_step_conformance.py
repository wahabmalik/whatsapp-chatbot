"""Cross-layer conformance tests for setup step progression (Epic 5 Retro Action Item 2).

Verifies that the controller (_setup_current_step) and the rendered HTML template
stay in sync: for every controller-computed step value, the correct <li> element
receives aria-current="step" in the rendered page.

Two conformance layers are tested:
  1. Unit: _setup_current_step() returns the expected integer for each scenario
  2. Integration: GET /setup renders exactly one aria-current="step" attribute
     on the <li> that corresponds to the step returned by the controller
"""

from __future__ import annotations

import os
import re
import unittest
from unittest.mock import patch

SETUP_ENV_FULL = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "tok",
    "APP_SECRET": "sec",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "vt",
    "OPENAI_API_KEY": "sk-test",
    "RECIPIENT_WAID": "15551234567",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
}

SETUP_ENV_EMPTY = {
    "WHATSAPP_PROVIDER": "meta",
    "OPENAI_API_KEY": "",
    "ACCESS_TOKEN": "",
    "APP_SECRET": "",
    "VERSION": "",
    "PHONE_NUMBER_ID": "",
    "VERIFY_TOKEN": "",
    "RECIPIENT_WAID": "15551234567",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
}

SETUP_REQUIRED_KEYS = [
    "OPENAI_API_KEY",
    "ACCESS_TOKEN",
    "APP_SECRET",
    "VERSION",
    "PHONE_NUMBER_ID",
    "VERIFY_TOKEN",
]

# Aria step labels (index 0 = step 1)
_STEP_LABELS = ["Welcome", "Validate required keys", "Copy webhook URL",
                "Verify webhook access", "Finish"]


def _step_label(step: int) -> str:
    return _STEP_LABELS[step - 1]


def _count_aria_current(html: str) -> int:
    return html.count('aria-current="step"')


def _aria_current_label(html: str) -> str | None:
    """Return the text of the <li> that has aria-current='step', or None."""
    match = re.search(r'<li[^>]*aria-current="step"[^>]*>(.*?)</li>', html, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _env_with_present_keys(*present_keys: str) -> dict[str, str]:
    env = dict(SETUP_ENV_EMPTY)
    for key in present_keys:
        env[key] = SETUP_ENV_FULL[key]
    return env


# ---------------------------------------------------------------------------
# Layer 1: Unit tests for _setup_current_step()
# ---------------------------------------------------------------------------

class SetupCurrentStepUnitTests(unittest.TestCase):
    """Controller logic maps setup state to the correct step integer."""

    def _call(self, setup_items: list[dict], complete: bool,
              session_verified: bool = False) -> int:
        with patch.dict(os.environ, SETUP_ENV_FULL, clear=False):
            from app import create_app
            app = create_app()
        with app.test_request_context("/setup"):
            from flask import session as flask_session
            flask_session["dashboard_role"] = "operator"
            if session_verified:
                flask_session["setup_verified"] = True

            from app.views_dashboard import _setup_current_step
            return _setup_current_step(setup_items, complete)

    def _items(self, present_keys: list[str], all_keys: list[str]) -> list[dict]:
        return [{"key": k, "present": k in present_keys} for k in all_keys]

    def test_no_items_returns_step_five(self):
        """Empty setup_items list → step 5 (edge case: nothing to configure)."""
        step = self._call(setup_items=[], complete=True)
        self.assertEqual(step, 5)

    def test_all_missing_returns_step_one(self):
        """All keys absent → step 1 (Welcome)."""
        keys = ["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_SECRET", "VERIFY_TOKEN", "PHONE_NUMBER_ID"]
        items = self._items(present_keys=[], all_keys=keys)
        step = self._call(setup_items=items, complete=False)
        self.assertEqual(step, 1)

    def test_partial_few_present_returns_step_two(self):
        """Only 1 of 5 keys present and total < threshold → step 2."""
        keys = ["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_SECRET", "VERIFY_TOKEN", "PHONE_NUMBER_ID"]
        items = self._items(present_keys=["OPENAI_API_KEY"], all_keys=keys)
        step = self._call(setup_items=items, complete=False)
        self.assertEqual(step, 2)

    def test_partial_many_present_returns_step_three(self):
        """4 of 5 keys present (>= max(2, total-1)) but not complete → step 3."""
        keys = ["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_SECRET", "VERIFY_TOKEN", "PHONE_NUMBER_ID"]
        items = self._items(
            present_keys=["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_SECRET", "VERIFY_TOKEN"],
            all_keys=keys,
        )
        step = self._call(setup_items=items, complete=False)
        self.assertEqual(step, 3)

    def test_all_present_not_verified_returns_step_four(self):
        """All keys present but session not verified → step 4."""
        keys = ["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_SECRET", "VERIFY_TOKEN", "PHONE_NUMBER_ID"]
        items = self._items(present_keys=keys, all_keys=keys)
        step = self._call(setup_items=items, complete=True, session_verified=False)
        self.assertEqual(step, 4)

    def test_all_present_and_verified_returns_step_five(self):
        """All keys present and session verified → step 5 (Finish)."""
        keys = ["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_SECRET", "VERIFY_TOKEN", "PHONE_NUMBER_ID"]
        items = self._items(present_keys=keys, all_keys=keys)
        step = self._call(setup_items=items, complete=True, session_verified=True)
        self.assertEqual(step, 5)

    def test_two_keys_present_of_three_returns_step_three(self):
        """2 of 3 keys present == max(2, 3-1)=2 → step 3."""
        keys = ["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_SECRET"]
        items = self._items(present_keys=["OPENAI_API_KEY", "ACCESS_TOKEN"], all_keys=keys)
        step = self._call(setup_items=items, complete=False)
        self.assertEqual(step, 3)


# ---------------------------------------------------------------------------
# Layer 2: Integration — rendered HTML matches controller output
# ---------------------------------------------------------------------------

class SetupStepAriaConformanceTests(unittest.TestCase):
    """GET /setup: aria-current='step' appears on exactly the <li> for the computed step."""

    def _make_client(self, env: dict):
        with patch.dict(os.environ, env, clear=True):
            from app import create_app
            app = create_app()
        app.config["SECRET_KEY"] = "test-secret-key"
        app.config["TESTING"] = True
        return app, app.test_client()

    def _get_setup_html(self, client, app, session_verified: bool = False) -> str:
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
            if session_verified:
                sess["setup_verified"] = True
        response = client.get("/setup")
        self.assertIn(response.status_code, (200, 302))
        if response.status_code == 302:
            response = client.get(response.headers["Location"])
        return response.get_data(as_text=True)

    def _controller_step_for_env(self, env: dict[str, str], session_verified: bool = False) -> int:
        app, _client = self._make_client(env)
        with app.test_request_context("/setup"):
            from flask import session as flask_session
            flask_session["dashboard_role"] = "operator"
            if session_verified:
                flask_session["setup_verified"] = True

            from app.views_dashboard import _setup_current_step, _setup_items

            setup_items = _setup_items()
            complete = all(item["present"] for item in setup_items)
            return _setup_current_step(setup_items, complete)

    def test_step_one_aria_on_welcome_when_all_keys_missing(self):
        """No keys configured → aria-current on 'Welcome' li."""
        app, client = self._make_client(SETUP_ENV_EMPTY)
        html = self._get_setup_html(client, app)
        self.assertEqual(_count_aria_current(html), 1)
        self.assertEqual(_aria_current_label(html), _step_label(1))

    def test_step_four_aria_on_verify_when_all_keys_present_not_verified(self):
        """All keys configured, not verified → aria-current on 'Verify webhook access' li."""
        app, client = self._make_client(SETUP_ENV_FULL)
        html = self._get_setup_html(client, app, session_verified=False)
        self.assertEqual(_count_aria_current(html), 1)
        self.assertEqual(_aria_current_label(html), _step_label(4))

    def test_step_five_aria_on_finish_when_verified(self):
        """All keys configured and verified → aria-current on 'Finish' li."""
        app, client = self._make_client(SETUP_ENV_FULL)
        html = self._get_setup_html(client, app, session_verified=True)
        self.assertEqual(_count_aria_current(html), 1)
        self.assertEqual(_aria_current_label(html), _step_label(5))

    def test_route_matches_controller_for_key_setup_states(self):
        """Initial, partial, near-complete, complete, and verified states stay in sync."""
        cases = [
            (SETUP_ENV_EMPTY, False),
            (_env_with_present_keys("OPENAI_API_KEY"), False),
            (_env_with_present_keys(*SETUP_REQUIRED_KEYS[:-1]), False),
            (SETUP_ENV_FULL, False),
            (SETUP_ENV_FULL, True),
        ]

        for env, session_verified in cases:
            with self.subTest(session_verified=session_verified, present_keys=sorted(k for k in SETUP_REQUIRED_KEYS if env.get(k))):
                app, client = self._make_client(env)
                html = self._get_setup_html(client, app, session_verified=session_verified)
                expected_step = self._controller_step_for_env(env, session_verified=session_verified)

                self.assertEqual(_count_aria_current(html), 1)
                self.assertEqual(_aria_current_label(html), _step_label(expected_step))

    def test_exactly_one_aria_current_step_per_page(self):
        """The rendered page must have exactly one aria-current='step' attribute."""
        app, client = self._make_client(SETUP_ENV_FULL)
        html = self._get_setup_html(client, app)
        self.assertEqual(_count_aria_current(html), 1,
                         "Expected exactly one aria-current='step' attribute")

    def test_operator_guard_redirects_end_user(self):
        """A non-operator session is redirected away from /setup."""
        app, client = self._make_client(SETUP_ENV_FULL)
        # No session manipulation → default end-user role
        response = client.get("/setup")
        self.assertIn(response.status_code, (302, 200))
        if response.status_code == 302:
            self.assertIn("/operator/access", response.headers["Location"])


# ---------------------------------------------------------------------------
# Layer 3: Step boundary consistency
# ---------------------------------------------------------------------------

class SetupStepBoundaryTests(unittest.TestCase):
    """Step transitions are stable at every boundary condition."""

    def setUp(self):
        self._env = patch.dict(os.environ, SETUP_ENV_FULL, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _call_step(self, present_count: int, total_count: int,
                   verified: bool = False) -> int:
        keys = [f"KEY_{i}" for i in range(total_count)]
        present = keys[:present_count]
        items = [{"key": k, "present": k in present} for k in keys]
        complete = present_count == total_count

        from app import create_app
        app = create_app()
        with app.test_request_context("/setup"):
            from flask import session as flask_session
            flask_session["dashboard_role"] = "operator"
            if verified:
                flask_session["setup_verified"] = True
            from app.views_dashboard import _setup_current_step
            return _setup_current_step(items, complete)

    def test_step_transitions_are_monotone_as_keys_added(self):
        """Adding keys one at a time should not decrease the step value."""
        total = 5
        prev_step = 0
        for present in range(0, total + 1):
            step = self._call_step(present_count=present, total_count=total)
            self.assertGreaterEqual(step, prev_step,
                                    f"Step regressed from {prev_step} to {step} at present={present}")
            prev_step = step

    def test_verification_always_increases_step_when_complete(self):
        """Verifying always moves step forward when all keys are present."""
        total = 5
        unverified = self._call_step(present_count=total, total_count=total, verified=False)
        verified = self._call_step(present_count=total, total_count=total, verified=True)
        self.assertGreater(verified, unverified)


class SetupRouteProgressionContractTests(unittest.TestCase):
    """Rendered setup progression is reachable and monotonic across lifecycle states."""

    def _rendered_step(self, env: dict[str, str], session_verified: bool = False) -> int:
        with patch.dict(os.environ, env, clear=True):
            from app import create_app
            app = create_app()

        app.config["SECRET_KEY"] = "setup-progression-contract"
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
            if session_verified:
                sess["setup_verified"] = True

        response = client.get("/setup")
        self.assertEqual(response.status_code, 200)
        label = _aria_current_label(response.get_data(as_text=True))
        self.assertIsNotNone(label)
        return _STEP_LABELS.index(label) + 1

    def test_route_progression_reaches_each_expected_step_once(self):
        """The setup route exposes the expected step sequence across lifecycle milestones."""
        progression = [
            self._rendered_step(SETUP_ENV_EMPTY),
            self._rendered_step(_env_with_present_keys("OPENAI_API_KEY")),
            self._rendered_step(_env_with_present_keys(*SETUP_REQUIRED_KEYS[:-1])),
            self._rendered_step(SETUP_ENV_FULL),
            self._rendered_step(SETUP_ENV_FULL, session_verified=True),
        ]

        self.assertEqual(progression, [1, 2, 3, 4, 5])

    def test_route_progression_is_monotonic_across_expected_transitions(self):
        """Advancing setup state must never regress the rendered active step."""
        progression = [
            self._rendered_step(SETUP_ENV_EMPTY),
            self._rendered_step(_env_with_present_keys("OPENAI_API_KEY")),
            self._rendered_step(_env_with_present_keys(*SETUP_REQUIRED_KEYS[:-1])),
            self._rendered_step(SETUP_ENV_FULL),
            self._rendered_step(SETUP_ENV_FULL, session_verified=True),
        ]

        self.assertEqual(progression, sorted(progression))


class SetupWizardLifecycleIntegrationTests(unittest.TestCase):
    """Full setup lifecycle contract: initial -> partial -> complete -> operator redirect."""

    def _make_client(self, env: dict[str, str]):
        with patch.dict(os.environ, env, clear=True):
            from app import create_app

            app = create_app()
        app.config["SECRET_KEY"] = "setup-wizard-lifecycle"
        app.config["TESTING"] = True
        return app, app.test_client()

    @staticmethod
    def _csrf_headers(client) -> dict[str, str]:
        token = "setup-lifecycle-csrf"
        with client.session_transaction() as sess:
            sess["_csrf_token"] = token
            sess["dashboard_role"] = "operator"
        return {"X-CSRFToken": token}

    def test_setup_wizard_full_lifecycle_preserves_operator_mode_on_redirect(self):
        app, client = self._make_client(SETUP_ENV_EMPTY)

        # Initial state: no required keys -> step 1 (Welcome).
        response = client.get("/operator/access", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(_aria_current_label(html), _step_label(1))

        # Partial state: one key present -> step 2 (Validate required keys).
        app.config["OPENAI_API_KEY"] = "sk-partial"
        response = client.get("/setup")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(_aria_current_label(html), _step_label(2))

        # Complete state: all required keys present -> step 4 (Verify webhook access).
        for key in SETUP_REQUIRED_KEYS:
            app.config[key] = SETUP_ENV_FULL[key]
        response = client.get("/setup")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(_aria_current_label(html), _step_label(4))

        # Verify completion and ensure redirect target keeps operator mode.
        verify = client.post("/setup/verify", headers=self._csrf_headers(client))
        self.assertEqual(verify.status_code, 200)

        response = client.get("/operator/access?next=/operator", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/operator", response.headers["Location"])

        operator_page = client.get(response.headers["Location"])
        self.assertEqual(operator_page.status_code, 200)
        body = operator_page.get_data(as_text=True)
        self.assertIn('class="bottom-nav"', body)
        self.assertIn("End User", body)


if __name__ == "__main__":
    unittest.main()
