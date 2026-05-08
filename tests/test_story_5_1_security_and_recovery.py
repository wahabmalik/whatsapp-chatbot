"""Tests for Story 5.1: CSRF protection, concurrency safety, and configuration recovery.

Verifies:
- Setup and dashboard write actions are protected against CSRF forgery
- Concurrent file writes don't cause corruption
- Configuration changes are backed up and auditable
- Operator can restore from backups
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

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


class Story51CsrfAndConfigRecoveryTests(unittest.TestCase):
    """Tests for CSRF protection and configuration recovery."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        # Suppress DEBUG import logs in tests
        with patch("logging.basicConfig"):
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

    # -----------------------------------------------------------------------
    # CSRF Protection Tests
    # -----------------------------------------------------------------------

    def test_protected_post_endpoints_reject_missing_csrf(self):
        """POST endpoints must reject requests without CSRF token."""
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
        """POST endpoints must reject requests with invalid CSRF token."""
        response = self.client.post(
            "/setup/verify",
            headers=self._csrf_headers("wrong-token"),
        )
        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertEqual(payload.get("ok"), False)
        self.assertNotIn("supersecret", response.get_data(as_text=True))

    def test_setup_openai_key_accepts_valid_csrf(self):
        """POST /setup/openai-key must accept requests with valid CSRF token."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write("VERIFY_TOKEN=verify-token\n")

            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            with patch("app.services.openai_service.refresh_openai_client"):
                response = self.client.post(
                    "/setup/openai-key",
                    data={"openai_api_key": "sk-valid-key"},
                    headers=self._csrf_headers(),
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["ok"], True)

    # -----------------------------------------------------------------------
    # Configuration Concurrency Tests
    # -----------------------------------------------------------------------

    def test_concurrent_env_writes_maintain_integrity(self):
        """Concurrent writes to .env file must not corrupt data."""
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
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=_writer, args=(i,)) for i in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

            self.assertFalse(any(thread.is_alive() for thread in threads), "writers did not finish")
            self.assertEqual(errors, [])

            with open(env_path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()

            # Ensure no duplicate keys
            openai_lines = [line for line in lines if line.startswith("OPENAI_API_KEY=")]
            self.assertEqual(len(openai_lines), 1, "OPENAI_API_KEY should appear exactly once")
            self.assertEqual(1, sum(1 for line in lines if line.startswith("VERIFY_TOKEN=")), "VERIFY_TOKEN corrupted")

    # -----------------------------------------------------------------------
    # Configuration Backup Tests
    # -----------------------------------------------------------------------

    def test_env_changes_create_backups(self):
        """Changing env values should create backup files."""
        from app.services.config_audit import list_available_backups

        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write("VERIFY_TOKEN=verify-token\n")

            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            with self.app.app_context():
                from app.views_dashboard import _set_env_value

                _set_env_value("OPENAI_API_KEY", "sk-test-1")

                backups = list_available_backups("env")
                self.assertGreater(len(backups), 0, "Should have created at least one backup")

    def test_agent_selection_changes_create_backups(self):
        """Changing agent selection should create backup files."""
        from app.services.config_audit import list_available_backups

        with tempfile.TemporaryDirectory() as tmp_dir:
            selection_path = os.path.join(tmp_dir, "data", "agent_selection.json")
            os.makedirs(os.path.dirname(selection_path), exist_ok=True)
            with open(selection_path, "w", encoding="utf-8") as fh:
                json.dump({"selected_agent_code": "old-agent"}, fh)

            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            with self.app.app_context():
                from app.services.agent_registry import set_selected_agent_code

                set_selected_agent_code("new-agent")

                backups = list_available_backups("agent_selection")
                self.assertGreater(len(backups), 0, "Should have created at least one backup")

    # -----------------------------------------------------------------------
    # Configuration Audit Log Tests
    # -----------------------------------------------------------------------

    def test_config_changes_recorded_in_audit_log(self):
        """Configuration changes should be recorded in audit log."""
        from app.services.config_audit import get_config_change_history

        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write("VERIFY_TOKEN=verify-token\n")

            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            with self.app.app_context():
                from app.views_dashboard import _set_env_value

                _set_env_value("OPENAI_API_KEY", "sk-test-key")

                changes = get_config_change_history(config_file=".env")
                self.assertGreater(len(changes), 0, "Should have recorded change in audit log")

                change = changes[0]
                self.assertEqual(change["config_file"], ".env")
                self.assertEqual(change["key"], "OPENAI_API_KEY")
                self.assertEqual(change["new_value"], "sk-test-key")
                self.assertIn("timestamp", change)

    # -----------------------------------------------------------------------
    # Configuration Restore Tests
    # -----------------------------------------------------------------------

    def test_audit_log_api_requires_operator_access(self):
        """GET /api/config/audit-log must require operator access."""
        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "end-user"

        response = self.client.get("/api/config/audit-log")
        self.assertIn(response.status_code, [302, 403])

    def test_audit_log_api_returns_changes(self):
        """GET /api/config/audit-log should return configuration changes."""
        from app.services.config_audit import record_config_change

        with tempfile.TemporaryDirectory() as tmp_dir:
            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            with self.app.app_context():
                record_config_change(
                    config_file=".env",
                    key="TEST_KEY",
                    old_value=None,
                    new_value="test_value",
                )

                response = self.client.get("/api/config/audit-log")
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["ok"], True)
                self.assertGreater(payload["total"], 0)

    def test_backups_list_api_requires_operator_access(self):
        """GET /api/config/backups must require operator access."""
        with self.client.session_transaction() as sess:
            sess["dashboard_role"] = "end-user"

        response = self.client.get("/api/config/backups?config_name=env")
        self.assertIn(response.status_code, [302, 403])

    def test_restore_api_requires_csrf(self):
        """POST /api/config/restore must require CSRF token."""
        response = self.client.post(
            "/api/config/restore",
            data={"config_name": "env", "backup_filename": "env_20240101_120000.bak"},
        )
        self.assertEqual(response.status_code, 403)

    def test_restore_api_rejects_invalid_config_name(self):
        """POST /api/config/restore should reject unknown configuration names."""
        response = self.client.post(
            "/api/config/restore",
            data={"config_name": "invalid_config", "backup_filename": "file.bak"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_restore_api_rejects_nonexistent_backup(self):
        """POST /api/config/restore should reject nonexistent backup files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.app.root_path = os.path.join(tmp_dir, "app")
            os.makedirs(self.app.root_path, exist_ok=True)

            response = self.client.post(
                "/api/config/restore",
                data={"config_name": "env", "backup_filename": "nonexistent.bak"},
                headers=self._csrf_headers(),
            )
            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
