"""Focused tests for Story 5.1: CSRF and config write safety."""

from __future__ import annotations

import os
import tempfile
import threading
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


class Story51CsrfTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
            sess["_csrf_token"] = "known-token"

    def tearDown(self):
        self._env_patch.stop()

    def _csrf_headers(self, value: str = "known-token") -> dict[str, str]:
        return {"X-CSRFToken": value}

    def test_protected_post_endpoints_reject_missing_csrf(self):
        verify_response = self.client.post("/setup/verify")
        self.assertEqual(verify_response.status_code, 403)

        openai_response = self.client.post(
            "/setup/openai-key",
            data={"openai_api_key": "sk-new"},
        )
        self.assertEqual(openai_response.status_code, 403)

        agents_response = self.client.post(
            "/agents",
            data={"agent_code": "bmad-agent-dev"},
        )
        self.assertEqual(agents_response.status_code, 403)

    def test_protected_post_endpoints_reject_invalid_csrf(self):
        response = self.client.post(
            "/setup/verify",
            headers=self._csrf_headers("wrong-token"),
        )
        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertEqual(payload.get("ok"), False)
        self.assertNotIn("supersecret", response.get_data(as_text=True))

    def test_setup_openai_key_requires_single_line_value(self):
        response = self.client.post(
            "/setup/openai-key",
            data={"openai_api_key": "sk-good\nsk-bad"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])


class Story51ConfigWriteSafetyTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
            sess["_csrf_token"] = "known-token"

    def tearDown(self):
        self._env_patch.stop()

    def _csrf_headers(self) -> dict[str, str]:
        return {"X-CSRFToken": "known-token"}

    def test_openai_key_save_refreshes_live_client_and_preserves_unrelated_env(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write("VERIFY_TOKEN=verify-token\nEXTRA_KEY=keep\n")

            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            with patch("app.services.openai_service.refresh_openai_client") as mock_refresh:
                response = self.client.post(
                    "/setup/openai-key",
                    data={"openai_api_key": "sk-live-updated"},
                    headers=self._csrf_headers(),
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.app.config["OPENAI_API_KEY"], "sk-live-updated")
            mock_refresh.assert_called_once_with("sk-live-updated")

            with open(env_path, "r", encoding="utf-8") as fh:
                content = fh.read()

            self.assertIn('OPENAI_API_KEY="sk-live-updated"', content)
            self.assertIn("VERIFY_TOKEN=verify-token", content)
            self.assertIn("EXTRA_KEY=keep", content)

    def test_concurrent_env_writes_do_not_interleave_or_duplicate_key(self):
        from app.views_dashboard import _set_env_value

        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write("VERIFY_TOKEN=verify-token\nEXTRA_KEY=keep\n")

            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            errors: list[Exception] = []

            def _writer(i: int):
                try:
                    with self.app.app_context():
                        _set_env_value("OPENAI_API_KEY", f"sk-write-{i}")
                except Exception as exc:  # pragma: no cover - defensive capture
                    errors.append(exc)

            # Keep this intentionally small to avoid long lock timeouts in CI while
            # still proving serialization under concurrent access.
            threads = [threading.Thread(target=_writer, args=(i,)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

            self.assertFalse(any(thread.is_alive() for thread in threads), "concurrent writers did not finish")
            self.assertEqual(errors, [])

            with open(env_path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()

            openai_lines = [line for line in lines if line.startswith("OPENAI_API_KEY=")]
            self.assertEqual(len(openai_lines), 1)
            self.assertIn("VERIFY_TOKEN=verify-token", lines)
            self.assertIn("EXTRA_KEY=keep", lines)


# ---------------------------------------------------------------------------
# Story 7.11 — SECRET_KEY hardcoded fallback absence test
# ---------------------------------------------------------------------------

class SecretKeyFallbackAbsenceTests(unittest.TestCase):
    """
    Asserts that when neither FLASK_SECRET_KEY nor SECRET_KEY env vars are set,
    the app starts with a non-empty, non-static SECRET_KEY generated via
    secrets.token_hex(32). Implements Epic 1 carry-forward.
    """

    def test_secret_key_is_set_when_env_vars_absent(self):
        """App must start with a non-empty SECRET_KEY even without env vars."""
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv"):
            from app import create_app

            app = create_app()
        self.assertTrue(bool(app.config.get("SECRET_KEY")), "SECRET_KEY must not be empty")

    def test_secret_key_is_not_static_hardcoded_fallback(self):
        """SECRET_KEY fallback must not be a well-known static string."""
        static_bad_values = {"secret", "dev", "changeme", "development", "test"}
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv"):
            from app import create_app

            app = create_app()
        key = str(app.config.get("SECRET_KEY", "")).lower()
        self.assertNotIn(key, static_bad_values, f"SECRET_KEY appears to be a static fallback: {key!r}")

    def test_secret_key_differs_between_two_app_instances_without_env(self):
        """Without env vars, each app creation generates a unique SECRET_KEY."""
        import importlib
        import app as app_module

        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv"):
            importlib.reload(app_module)
            app1 = app_module.create_app()
            app2 = app_module.create_app()
        self.assertNotEqual(
            app1.config.get("SECRET_KEY"),
            app2.config.get("SECRET_KEY"),
            "Two app instances without SECRET_KEY env var must generate distinct keys",
        )

    def test_secret_key_uses_env_var_when_provided(self):
        """When FLASK_SECRET_KEY is set, app must use that value."""
        expected = "explicit-test-secret-key-1234567890"
        with patch.dict(os.environ, {"FLASK_SECRET_KEY": expected}, clear=False):
            from app import create_app

            app = create_app()
        self.assertEqual(app.config.get("SECRET_KEY"), expected)


if __name__ == "__main__":
    unittest.main()
