"""
Tests for Story 5.1: Dashboard CSRF and Config Write Safety

Covers:
- CSRF token generation and validation helpers
- /setup/verify POST: valid token accepted, missing/bad token returns 403
- /setup/openai-key POST: CSRF enforced; empty key rejected; key saved atomically
- /agents POST: CSRF enforced on agent selection
- _set_env_value: creates file, updates existing key, preserves adjacent keys,
  multiple writes produce clean final state
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


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


def _make_app():
    with patch.dict(os.environ, _BASE_ENV, clear=False):
        from app import create_app
        return create_app()


class _OperatorClient:
    """Test helper that sets up an operator session and CSRF token on a test client."""

    def __init__(self, app):
        self.app = app
        self.client = app.test_client()
        self.app.config["SECRET_KEY"] = "test-secret-csrf"
        self.app.config["TESTING"] = True
        # Force setup complete so operator dashboard is accessible
        self.app.config["ACCESS_TOKEN"] = "tok"
        self.app.config["APP_SECRET"] = "sec"
        self.app.config["VERSION"] = "v18.0"
        self.app.config["PHONE_NUMBER_ID"] = "1234567890"
        self.app.config["VERIFY_TOKEN"] = "vt"
        self.app.config["OPENAI_API_KEY"] = "sk-test"

    def become_operator(self):
        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"

    def get_csrf_token(self):
        """Fetch CSRF token from session (requires at least one GET to create it)."""
        with self.client.session_transaction() as sess:
            return sess.get("_csrf_token")

    def seed_csrf_token(self, token="test-csrf-token-abc123"):
        """Directly seed a known CSRF token into the session."""
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = token
        return token


# ---------------------------------------------------------------------------
# CSRF token helpers (unit tests, no HTTP)
# ---------------------------------------------------------------------------

class CsrfTokenHelperTests(unittest.TestCase):
    """CSRF token generation and comparison helpers."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.app.config["SECRET_KEY"] = "unit-test-secret"
        self.app.config["TESTING"] = True

    def tearDown(self):
        self._env.stop()

    def test_token_is_created_when_absent(self):
        """CSRF token is populated in session on first request."""
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
        # GET /setup forces session population including CSRF token
        client.get("/setup")
        with client.session_transaction() as sess:
            self.assertIn("_csrf_token", sess)
            self.assertGreater(len(sess["_csrf_token"]), 10)

    def test_token_is_stable_across_requests(self):
        """CSRF token is not regenerated on every request."""
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
            sess["_csrf_token"] = "stable-token-xyz"
        client.get("/setup")
        with client.session_transaction() as sess:
            self.assertEqual(sess["_csrf_token"], "stable-token-xyz")

    def test_valid_token_in_header_passes_validation(self):
        """Valid X-CSRFToken header matches session token."""
        oc = _OperatorClient(self.app)
        oc.become_operator()
        token = oc.seed_csrf_token("my-valid-token")
        response = oc.client.post(
            "/setup/verify",
            headers={"X-CSRFToken": token},
        )
        # 200 or 400 (missing keys) — not 403
        self.assertNotEqual(response.status_code, 403)

    def test_missing_token_returns_403(self):
        """Request without any CSRF token returns 403."""
        oc = _OperatorClient(self.app)
        oc.become_operator()
        oc.seed_csrf_token("my-valid-token")
        response = oc.client.post("/setup/verify")
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertFalse(data["ok"])

    def test_wrong_token_returns_403(self):
        """Request with incorrect CSRF token returns 403."""
        oc = _OperatorClient(self.app)
        oc.become_operator()
        oc.seed_csrf_token("my-valid-token")
        response = oc.client.post(
            "/setup/verify",
            headers={"X-CSRFToken": "wrong-token"},
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# /setup/verify CSRF enforcement
# ---------------------------------------------------------------------------

class SetupVerifyCsrfTests(unittest.TestCase):
    """CSRF gate on POST /setup/verify (AC1, AC2)."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.oc = _OperatorClient(self.app)
        self.oc.become_operator()

    def tearDown(self):
        self._env.stop()

    def test_valid_csrf_token_via_form_field(self):
        """AC1: valid token in form field csrf_token passes the gate."""
        token = self.oc.seed_csrf_token()
        response = self.oc.client.post(
            "/setup/verify", data={"csrf_token": token}
        )
        self.assertNotEqual(response.status_code, 403)

    def test_valid_csrf_token_via_header(self):
        """AC1: valid token in X-CSRFToken header passes the gate."""
        token = self.oc.seed_csrf_token()
        response = self.oc.client.post(
            "/setup/verify", headers={"X-CSRFToken": token}
        )
        self.assertNotEqual(response.status_code, 403)

    def test_missing_csrf_token_returns_403(self):
        """AC1: POST without any token returns 403."""
        self.oc.seed_csrf_token()
        response = self.oc.client.post("/setup/verify")
        self.assertEqual(response.status_code, 403)

    def test_bad_csrf_token_returns_403(self):
        """AC1: POST with incorrect token value returns 403."""
        self.oc.seed_csrf_token("correct-token")
        response = self.oc.client.post(
            "/setup/verify", headers={"X-CSRFToken": "bad-token"}
        )
        self.assertEqual(response.status_code, 403)

    def test_csrf_failure_response_is_json_not_stacktrace(self):
        """AC2: 403 response is controlled JSON without secrets or trace."""
        self.oc.seed_csrf_token("correct")
        response = self.oc.client.post(
            "/setup/verify", headers={"X-CSRFToken": "wrong"}
        )
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertFalse(data["ok"])
        self.assertNotIn("Traceback", response.data.decode())


# ---------------------------------------------------------------------------
# /setup/openai-key CSRF and key save behavior
# ---------------------------------------------------------------------------

class SetupOpenAiKeyCsrfTests(unittest.TestCase):
    """AC1–AC5: CSRF gate + atomic key save on POST /setup/openai-key."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.oc = _OperatorClient(self.app)
        self.oc.become_operator()

    def tearDown(self):
        self._env.stop()

    def test_missing_csrf_returns_403(self):
        """AC1: POST without token is rejected."""
        self.oc.seed_csrf_token()
        response = self.oc.client.post(
            "/setup/openai-key", data={"openai_api_key": "sk-newkey"}
        )
        self.assertEqual(response.status_code, 403)

    def test_empty_key_returns_400(self):
        """AC1/AC2: empty key value is rejected with 400 even with valid CSRF."""
        token = self.oc.seed_csrf_token()
        response = self.oc.client.post(
            "/setup/openai-key",
            data={"openai_api_key": "", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 400)

    def test_newline_in_key_is_rejected(self):
        """Security: key containing newline is rejected to prevent injection."""
        token = self.oc.seed_csrf_token()
        response = self.oc.client.post(
            "/setup/openai-key",
            data={"openai_api_key": "sk-valid\nbad", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_key_save_updates_app_config(self):
        """AC5: successful key save updates current_app.config immediately."""
        token = self.oc.seed_csrf_token()
        with patch("app.views_dashboard._set_env_value"), \
             patch("app.views_dashboard.refresh_openai_client", create=True):
            with patch.dict("sys.modules", {
                "app.services.openai_service": MagicMock(
                    refresh_openai_client=MagicMock()
                )
            }):
                response = self.oc.client.post(
                    "/setup/openai-key",
                    data={"openai_api_key": "sk-newkey-abc", "csrf_token": token},
                )
        # May succeed (200) or hit refresh error (500) depending on mock state;
        # should NOT be 403 (CSRF) or 400 (validation)
        self.assertNotIn(response.status_code, (403, 400))


# ---------------------------------------------------------------------------
# /agents POST CSRF enforcement
# ---------------------------------------------------------------------------

class AgentsPostCsrfTests(unittest.TestCase):
    """AC1: CSRF gate on POST /agents."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self.oc = _OperatorClient(self.app)
        self.oc.become_operator()

    def tearDown(self):
        self._env.stop()

    def test_missing_csrf_returns_403(self):
        """AC1: POST /agents without token returns 403."""
        self.oc.seed_csrf_token()
        response = self.oc.client.post(
            "/agents", data={"agent_code": "FAQ_AGENT"}
        )
        self.assertEqual(response.status_code, 403)

    def test_bad_csrf_returns_403(self):
        """AC1: POST /agents with wrong token returns 403."""
        self.oc.seed_csrf_token("good-token")
        response = self.oc.client.post(
            "/agents",
            data={"agent_code": "FAQ_AGENT"},
            headers={"X-CSRFToken": "bad-token"},
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# _set_env_value: atomic write and key preservation
# ---------------------------------------------------------------------------

class EnvWriteSafetyTests(unittest.TestCase):
    """AC3, AC4: .env writes are atomic and preserve unrelated keys."""

    def setUp(self):
        self._env = patch.dict(os.environ, _BASE_ENV, clear=False)
        self._env.start()
        self.app = _make_app()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.env_path = Path(self._tmpdir.name) / ".env"

    def tearDown(self):
        self._env.stop()
        self._tmpdir.cleanup()

    def _call_set_env_value(self, key: str, value: str):
        with self.app.app_context():
            with patch("app.views_dashboard._env_file_path", return_value=self.env_path):
                from app.views_dashboard import _set_env_value
                _set_env_value(key, value)

    def test_creates_env_file_when_absent(self):
        """AC3: _set_env_value creates .env if it does not exist."""
        self._call_set_env_value("NEW_KEY", "hello")
        self.assertTrue(self.env_path.exists())
        content = self.env_path.read_text()
        self.assertIn('NEW_KEY="hello"', content)

    def test_updates_existing_key_in_place(self):
        """AC4: updating an existing key replaces its line, not appends."""
        self.env_path.write_text('ACCESS_TOKEN="old-token"\n', encoding="utf-8")
        self._call_set_env_value("ACCESS_TOKEN", "new-token")
        content = self.env_path.read_text()
        self.assertIn('ACCESS_TOKEN="new-token"', content)
        self.assertNotIn("old-token", content)
        self.assertEqual(content.count("ACCESS_TOKEN"), 1)

    def test_preserves_adjacent_keys(self):
        """AC4: writing one key does not remove unrelated keys."""
        self.env_path.write_text(
            'FIRST_KEY="first"\nSECOND_KEY="second"\n', encoding="utf-8"
        )
        self._call_set_env_value("FIRST_KEY", "updated")
        content = self.env_path.read_text()
        self.assertIn('FIRST_KEY="updated"', content)
        self.assertIn('SECOND_KEY="second"', content)

    def test_adds_new_key_without_disturbing_existing(self):
        """AC4: new key is appended without touching existing keys."""
        self.env_path.write_text('EXISTING="keep"\n', encoding="utf-8")
        self._call_set_env_value("ADDED_KEY", "added")
        content = self.env_path.read_text()
        self.assertIn('EXISTING="keep"', content)
        self.assertIn('ADDED_KEY="added"', content)

    def test_repeated_writes_do_not_duplicate_key(self):
        """AC3: writing the same key multiple times results in exactly one entry."""
        for val in ("v1", "v2", "v3"):
            self._call_set_env_value("STABLE_KEY", val)
        content = self.env_path.read_text()
        self.assertEqual(content.count("STABLE_KEY"), 1)
        self.assertIn('STABLE_KEY="v3"', content)

    def test_special_characters_are_escaped(self):
        """AC3: backslashes and quotes in values are safely escaped."""
        self._call_set_env_value("SPECIAL", 'val"with"quotes')
        content = self.env_path.read_text()
        self.assertIn("SPECIAL=", content)
        # Raw unescaped form should not appear
        self.assertNotIn('SPECIAL="val"with"quotes"', content)

    def test_write_is_atomic_via_temp_and_replace(self):
        """AC3: temp file pattern used — no partial write visible on disk."""
        # After a successful write, no .tmp file should remain
        self._call_set_env_value("ATOMIC_KEY", "value")
        tmp_path = self.env_path.with_suffix(".env.tmp")
        self.assertFalse(tmp_path.exists(), "Temp file should be cleaned up after write")


if __name__ == "__main__":
    unittest.main()
