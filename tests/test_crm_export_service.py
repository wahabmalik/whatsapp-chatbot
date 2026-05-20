from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from flask import Flask


class CrmExportServiceTests(unittest.TestCase):
    def _app(self) -> Flask:
        app = Flask(__name__)
        app.config["CRM_EXPORT_ENABLED"] = False
        app.config["CRM_EXPORT_WEBHOOK_URL"] = ""
        app.config["CRM_EXPORT_API_KEY"] = ""
        app.config["CRM_EXPORT_TIMEOUT_SECONDS"] = 5.0
        return app

    def test_export_skips_when_disabled(self):
        from app.services.crm_export import export_analytics_event_to_crm

        app = self._app()
        event = {"stage": "outbound_outcome", "correlation_id": "corr-1"}

        with patch("requests.post") as mocked_post:
            exported = export_analytics_event_to_crm(app, event)

        self.assertFalse(exported)
        mocked_post.assert_not_called()

    def test_export_posts_event_when_enabled(self):
        from app.services.crm_export import export_analytics_event_to_crm

        app = self._app()
        app.config["CRM_EXPORT_ENABLED"] = True
        app.config["CRM_EXPORT_WEBHOOK_URL"] = "https://crm.example.test/hooks/events"
        app.config["CRM_EXPORT_API_KEY"] = "secret-key"

        response = Mock()
        response.status_code = 202
        response.raise_for_status = Mock()

        event = {"stage": "outbound_outcome", "correlation_id": "corr-2"}
        with patch("requests.post", return_value=response) as mocked_post:
            exported = export_analytics_event_to_crm(app, event)

        self.assertTrue(exported)
        mocked_post.assert_called_once()
        _, kwargs = mocked_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")
        self.assertEqual(kwargs["json"]["event"]["correlation_id"], "corr-2")

    def test_emit_analytics_event_triggers_crm_export(self):
        from app.services.conversation_analytics import emit_analytics_event

        app = self._app()
        with patch("app.services.conversation_analytics.export_analytics_event_to_crm", return_value=True) as mocked:
            event = emit_analytics_event(
                app,
                stage="outbound_outcome",
                correlation_id="corr-3",
                user_id="15551234567",
                conversation_id="conv-3",
                outcome_status="sent",
                details={"channel": "messenger"},
            )

        self.assertEqual(event["stage"], "outbound_outcome")
        mocked.assert_called_once()


class CrmConfigValidationTests(unittest.TestCase):
    def test_validate_config_ignores_crm_url_when_disabled(self):
        from app.config import validate_config

        app = Flask(__name__)
        app.config.update(
            {
                "WHATSAPP_PROVIDER": "evolution",
                "OPENAI_API_KEY": "sk-test-key",
                "EVOLUTION_API_URL": "https://example.test",
                "EVOLUTION_API_KEY": "evolution-key",
                "EVOLUTION_INSTANCE_NAME": "instance",
                "ONBOARDING_INSTANCE_MODE": "auto",
                "STATE_STORE_BACKEND": "memory",
                "OUTBOUND_CHANNEL": "whatsapp",
                "CRM_EXPORT_ENABLED": False,
                "CRM_EXPORT_WEBHOOK_URL": "not-a-url",
            }
        )

        errors = validate_config(app)
        self.assertFalse(any("CRM_EXPORT_WEBHOOK_URL" in item for item in errors))

    def test_validate_config_requires_webhook_when_enabled(self):
        from app.config import validate_config

        app = Flask(__name__)
        app.config.update(
            {
                "WHATSAPP_PROVIDER": "evolution",
                "OPENAI_API_KEY": "sk-test-key",
                "EVOLUTION_API_URL": "https://example.test",
                "EVOLUTION_API_KEY": "evolution-key",
                "EVOLUTION_INSTANCE_NAME": "instance",
                "ONBOARDING_INSTANCE_MODE": "auto",
                "STATE_STORE_BACKEND": "memory",
                "OUTBOUND_CHANNEL": "whatsapp",
                "CRM_EXPORT_ENABLED": True,
                "CRM_EXPORT_WEBHOOK_URL": "",
            }
        )

        errors = validate_config(app)
        self.assertTrue(any("CRM_EXPORT_ENABLED requires CRM_EXPORT_WEBHOOK_URL" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
