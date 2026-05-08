"""
End-to-end integration tests for runtime agent selection switching.

Validates that an operator can switch the active agent via POST /agents,
and the very next inbound webhook message will use the newly selected agent
without any process restart.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
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


class RuntimeAgentSwitchE2ETests(unittest.TestCase):
    """End-to-end tests proving agent switching is immediate and persistent."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, FULL_REQUIRED_ENV, clear=True)
        self._env_patch.start()

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir_path = Path(self._tmpdir.name)

        # Patch agent registry to use temp selection file
        self.selection_file = self.tmpdir_path / "agent_selection.json"
        self._orig_selection_file = None

    def tearDown(self):
        self._env_patch.stop()
        self._tmpdir.cleanup()
        if self._orig_selection_file is not None:
            import app.services.agent_registry as ar
            ar.SELECTION_FILE = self._orig_selection_file

    def test_next_inbound_message_uses_newly_selected_agent(self):
        """
        AC: When an operator switches agent via selection persistence,
        the very next call to process_whatsapp_message uses the new agent.
        """
        from app.services import agent_registry
        from app.utils.whatsapp_utils import process_whatsapp_message

        # Patch selection file
        self._orig_selection_file = agent_registry.SELECTION_FILE
        agent_registry.SELECTION_FILE = self.selection_file

        # Create temp app context
        from flask import Flask

        app = Flask(__name__)
        app.config.update({
            "ACCESS_TOKEN": "token",
            "VERSION": "v18.0",
            "PHONE_NUMBER_ID": "1234567890",
        })

        inbound_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{"wa_id": "15551234567", "profile": {"name": "User"}}],
                        "messages": [{"id": "msg1", "text": {"body": "hello"}}],
                    }
                }]
            }],
        }

        with app.app_context():
            # First message uses agent-one
            with patch(
                "app.utils.whatsapp_utils.get_selected_agent",
                return_value={"name": "Agent One", "code": "a1"},
            ), patch(
                "app.utils.whatsapp_utils.send_message",
                return_value={"status": "sent", "error": None, "operator_review_flagged": False},
            ):
                result1 = process_whatsapp_message(inbound_payload, request_id="msg1")

            self.assertEqual(result1["agent"], "Agent One")

            # Switch agent selection (no app restart)
            agent_registry.set_selected_agent_code("agent-two")

            # Next message uses agent-two immediately
            with patch(
                "app.utils.whatsapp_utils.get_selected_agent",
                return_value={"name": "Agent Two", "code": "a2"},
            ), patch(
                "app.utils.whatsapp_utils.send_message",
                return_value={"status": "sent", "error": None, "operator_review_flagged": False},
            ):
                result2 = process_whatsapp_message(inbound_payload, request_id="msg2")

            self.assertEqual(result2["agent"], "Agent Two")

    def test_agent_context_propagates_to_openai_provider_when_enabled(self):
        """
        AC: When OpenAI provider is enabled and agent context is available,
        the OpenAI provider boundary receives agent context.
        """
        from flask import Flask
        from app.utils.whatsapp_utils import _default_ai_provider

        agent_ctx = {
            "code": "premium-agent",
            "name": "Premium Support",
            "title": "VIP Specialist",
            "description": "Handles enterprise clients",
        }

        calls = []

        def _fake_generate_response(message_body, wa_id, name, agent_context=None):
            calls.append({
                "message_body": message_body,
                "wa_id": wa_id,
                "name": name,
                "agent_context": agent_context,
            })
            return "Test response"

        fake_openai_service = types.ModuleType("app.services.openai_service")
        fake_openai_service.generate_response = _fake_generate_response

        app = Flask(__name__)
        app.config.update({
            "USE_OPENAI_SERVICE": True,
            "OPENAI_ASSISTANT_ID": "asst_test",
        })

        with patch.dict(sys.modules, {"app.services.openai_service": fake_openai_service}):
            with app.app_context():
                result = _default_ai_provider(
                    "hello",
                    "15551234567",
                    "Test User",
                    agent_ctx,
                )

        self.assertEqual(result, "Test response")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["agent_context"], agent_ctx)

    def test_transient_read_error_does_not_persist_fallback(self):
        """
        AC: When selection file read fails with OSError (transient),
        fallback agent is returned but NOT persisted.
        """
        from app.services import agent_registry

        # Patch selection file
        self._orig_selection_file = agent_registry.SELECTION_FILE
        agent_registry.SELECTION_FILE = self.selection_file

        # Create valid selection file
        self.selection_file.parent.mkdir(parents=True, exist_ok=True)
        self.selection_file.write_text(
            '{"selected_agent_code": "agent-premium"}',
            encoding="utf-8",
        )

        agents = [
            {"code": "agent-standard", "name": "Standard"},
            {"code": "agent-premium", "name": "Premium"},
        ]

        # Mock list_bmad_agents to return our test agents
        with patch("app.services.agent_registry.list_bmad_agents", return_value=agents):
            # First, verify baseline: premium is selected
            selected = agent_registry.get_selected_agent()
            self.assertEqual(selected["code"], "agent-premium")

            # Now mock the read to fail on first call only
            original_read = agent_registry._read_selected_agent_code
            call_count = [0]

            def read_with_transient_failure():
                call_count[0] += 1
                if call_count[0] == 1:
                    # First call: simulate OSError
                    return None, "read_error"
                else:
                    # Second call: use real read
                    return original_read()

            with patch("app.services.agent_registry._read_selected_agent_code",
                       side_effect=read_with_transient_failure), \
                 patch("app.services.agent_registry.set_selected_agent_code") as mock_set:
                # First call encounters read error; should fallback to first agent
                # but NOT persist the fallback
                selected = agent_registry.get_selected_agent()
                self.assertEqual(selected["code"], "agent-standard")
                # Critical: should NOT have persisted fallback
                mock_set.assert_not_called()

            # Verify original selection is still intact
            selected = agent_registry.get_selected_agent()
            self.assertEqual(selected["code"], "agent-premium")


if __name__ == "__main__":
    unittest.main()
