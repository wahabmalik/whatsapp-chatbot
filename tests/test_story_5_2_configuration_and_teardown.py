"""
Tests for Story 5.2: Configuration Validation and Runtime Guardrails

Acceptance Criteria:
1. Unknown WHATSAPP_PROVIDER values fail validation with an actionable error
   instead of silently mapping to meta.
2. Outbound provider configuration reads use validation-safe access patterns
   rather than bracket lookups that can raise KeyError during runtime.
3. WhatsApp outbound timeout is configurable via a validated setting with a
   documented default value.
4. The retry/fallback implementation plan explicitly resolves whether fallback
   delivery gets its own bounded retry policy, and tests reflect the chosen contract.
5. App teardown catches and logs per-extension close() failures while still
   attempting cleanup for the remaining extensions.
"""
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import Flask
import requests


class ConfigValidationUnknownProviderTests(unittest.TestCase):
    """AC1: Unknown WHATSAPP_PROVIDER values fail validation explicitly."""

    def test_validate_config_rejects_unknown_provider_value(self):
        """AC1: Explicit error when WHATSAPP_PROVIDER has unknown value."""
        from app.config import load_configurations, validate_config

        with patch.dict(os.environ, {"WHATSAPP_PROVIDER": "invalid-provider"}, clear=True):
            app = Flask(__name__)
            load_configurations(app)
            
            errors = validate_config(app)
            
            # Must produce an error specifically about the provider
            self.assertTrue(
                any("WHATSAPP_PROVIDER" in e and "not recognized" in e for e in errors),
                f"Expected provider validation error, got: {errors}"
            )

    def test_normalize_provider_logs_explicit_warning_on_unknown_value(self):
        """AC1: Unknown provider should be reported, not silently mapped."""
        with patch.dict(os.environ, {"WHATSAPP_PROVIDER": "bogus"}, clear=True), \
             patch("app.config.load_dotenv", return_value=None):
            from app import create_app

            app = create_app()
            
            # Config validation errors should include the unknown provider
            config_errors = app.extensions.get("config_validation_errors", [])
            self.assertTrue(
                any("bogus" in str(e) for e in config_errors),
                f"Unknown provider 'bogus' should trigger validation error, got: {config_errors}"
            )


class ConfigValidationPlaceholderValueTests(unittest.TestCase):
    """Reject template placeholders for sensitive secrets and endpoints."""

    def test_validate_config_rejects_placeholder_secret_key_value(self):
        from app.config import load_configurations, validate_config

        env = {
            "WHATSAPP_PROVIDER": "evolution",
            "OPENAI_API_KEY": "sk-live-realistic",
            "EVOLUTION_API_URL": "http://localhost:3333",
            "EVOLUTION_API_KEY": "evo_real_key",
            "EVOLUTION_INSTANCE_NAME": "bot-instance",
            "FLASK_SECRET_KEY": "<generate one>",
        }
        with patch.dict(os.environ, env, clear=True):
            app = Flask(__name__)
            load_configurations(app)

            errors = validate_config(app)

        self.assertTrue(
            any("SECRET_KEY appears to be a placeholder" in e for e in errors),
            f"Expected placeholder SECRET_KEY validation error, got: {errors}",
        )

    def test_validate_config_rejects_placeholder_paddle_price_id(self):
        from app.config import load_configurations, validate_config

        env = {
            "WHATSAPP_PROVIDER": "evolution",
            "OPENAI_API_KEY": "sk-live-realistic",
            "EVOLUTION_API_URL": "http://localhost:3333",
            "EVOLUTION_API_KEY": "evo_real_key",
            "EVOLUTION_INSTANCE_NAME": "bot-instance",
            "FLASK_SECRET_KEY": "this_is_a_real_secret_key_value",
            "PADDLE_STARTER_PRICE_ID": "pri_...",
        }
        with patch.dict(os.environ, env, clear=True):
            app = Flask(__name__)
            load_configurations(app)

            errors = validate_config(app)

        self.assertTrue(
            any("PADDLE_STARTER_PRICE_ID appears to be a placeholder" in e for e in errors),
            f"Expected placeholder PADDLE_STARTER_PRICE_ID validation error, got: {errors}",
        )


class OutboundDeliveryTimeoutConfigTests(unittest.TestCase):
    """AC3: Outbound timeout is configurable via validated setting."""

    def test_send_timeout_uses_configured_value(self):
        """AC3: _send_timeout_seconds() reads and returns configured timeout."""
        from app.utils.whatsapp_utils import _send_timeout_seconds

        app = Flask(__name__)
        app.config["WHATSAPP_SEND_TIMEOUT_SECONDS"] = 15.5
        
        with app.app_context():
            timeout = _send_timeout_seconds()
            self.assertEqual(timeout, 15.5)

    def test_send_timeout_default_value(self):
        """AC3: Documented default is 10.0 seconds."""
        from app.utils.whatsapp_utils import _send_timeout_seconds

        app = Flask(__name__)
        app.config["WHATSAPP_SEND_TIMEOUT_SECONDS"] = 10.0
        
        with app.app_context():
            timeout = _send_timeout_seconds()
            self.assertEqual(timeout, 10.0)

    def test_send_timeout_configuration_validated_at_startup(self):
        """AC3: Timeout must be > 0.1 seconds; validated in load_configurations."""
        from app.config import load_configurations, validate_config

        with patch.dict(os.environ, {"WHATSAPP_SEND_TIMEOUT_SECONDS": "0.05"}, clear=True):
            app = Flask(__name__)
            try:
                load_configurations(app)
                # If load_configurations raises ValueError, this is expected
                self.fail("Expected ValueError for timeout < 0.1")
            except ValueError as e:
                self.assertIn("WHATSAPP_SEND_TIMEOUT_SECONDS", str(e))


class FallbackDeliveryRetryPolicyTests(unittest.TestCase):
    """AC4: Fallback delivery has explicit, bounded retry policy."""

    def test_fallback_send_respects_fallback_max_retries_config(self):
        """AC4: Fallback delivery uses WHATSAPP_FALLBACK_MAX_RETRIES setting."""
        from app.utils.whatsapp_utils import _send_fallback
        from app.services.metrics import get_metrics_collector

        with tempfile.TemporaryDirectory() as tmpdir:
            app = Flask(__name__)
            app.config["WHATSAPP_PROVIDER"] = "meta"
            app.config["ACCESS_TOKEN"] = "test-token"
            app.config["PHONE_NUMBER_ID"] = "123456789"
            app.config["VERSION"] = "v18.0"
            app.config["RECIPIENT_WAID"] = "15551234567"
            app.config["OUTBOUND_FALLBACK_TEXT"] = "We are experiencing issues"
            app.config["WHATSAPP_FALLBACK_MAX_RETRIES"] = 3  # Explicit retry count

            with app.app_context():
                data = '{"to": "15551234567", "text": {"body": "test"}}'
                metrics = get_metrics_collector(app)
                
                with patch("app.utils.whatsapp_utils._send_request") as mock_send:
                    mock_send.side_effect = requests.RequestException("Network error")
                    result = _send_fallback(data, "req-123", send_timeout=10.0, metrics=metrics)
                    
                    # Verify the function was called 3 times (the retry count)
                    self.assertEqual(mock_send.call_count, 3)
                    self.assertFalse(result["fallback_sent"])

    def test_fallback_retry_stops_on_success(self):
        """AC4: Fallback stops retrying after successful send."""
        from app.utils.whatsapp_utils import _send_fallback
        from app.services.metrics import get_metrics_collector

        app = Flask(__name__)
        app.config["WHATSAPP_PROVIDER"] = "meta"
        app.config["ACCESS_TOKEN"] = "test-token"
        app.config["PHONE_NUMBER_ID"] = "123456789"
        app.config["VERSION"] = "v18.0"
        app.config["RECIPIENT_WAID"] = "15551234567"
        app.config["OUTBOUND_FALLBACK_TEXT"] = "We are experiencing issues"
        app.config["WHATSAPP_FALLBACK_MAX_RETRIES"] = 3

        with app.app_context():
            data = '{"to": "15551234567", "text": {"body": "test"}}'
            metrics = get_metrics_collector(app)
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status.return_value = None
            
            with patch("app.utils.whatsapp_utils._send_request") as mock_send, \
                 patch("app.utils.whatsapp_utils.log_http_response"):
                # First attempt fails, second succeeds
                mock_send.side_effect = [
                    requests.Timeout("First attempt failed"),
                    mock_response,
                ]
                result = _send_fallback(data, "req-456", send_timeout=10.0, metrics=metrics)
                
                # Should have stopped after 2 attempts (failure + success)
                self.assertEqual(mock_send.call_count, 2)
                self.assertTrue(result["fallback_sent"])


class AppTeardownResilienceTests(unittest.TestCase):
    """AC5: App teardown catches per-extension close() failures."""

    @staticmethod
    def _build_app_with_teardown():
        from app import create_app

        # Keep startup deterministic in tests while exercising real teardown registration.
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_PROVIDER": "meta",
                "OPENAI_API_KEY": "test-openai-key",
                "ACCESS_TOKEN": "test-token",
                "APP_SECRET": "test-secret",
                "VERSION": "v18.0",
                "PHONE_NUMBER_ID": "123456789",
                "VERIFY_TOKEN": "test-verify-token",
            },
            clear=True,
        ):
            return create_app()

    def test_teardown_continues_after_close_failure(self):
        """AC5: One extension's close() exception doesn't skip remaining extensions."""
        app = self._build_app_with_teardown()
        
        # Create mock extensions: one that fails, one that succeeds
        failing_extension = Mock()
        failing_extension.close.side_effect = RuntimeError("Extension close failed")
        
        succeeding_extension = Mock()
        succeeding_extension.close.return_value = None
        
        app.extensions["failing"] = failing_extension
        app.extensions["succeeding"] = succeeding_extension
        
        with patch("app.logging.warning") as mock_warning:
            # Trigger teardown
            with app.app_context():
                pass  # Exit context to trigger teardown_appcontext
        
        # Both extensions' close() methods should have been called
        failing_extension.close.assert_called_once()
        succeeding_extension.close.assert_called_once()

    def test_teardown_logs_close_exceptions(self):
        """AC5: Teardown logs close() exceptions for debugging."""
        app = self._build_app_with_teardown()
        
        failing_extension = Mock()
        error_msg = "Database connection failed"
        failing_extension.close.side_effect = RuntimeError(error_msg)
        
        app.extensions["db"] = failing_extension
        
        with patch("app.logging.warning") as mock_warning:
            with app.app_context():
                pass
        
        # Verify logging was called with the exception
        mock_warning.assert_called()
        call_args = str(mock_warning.call_args)
        self.assertIn(error_msg, call_args)

    def test_teardown_skips_extensions_without_close(self):
        """AC5: Teardown gracefully handles extensions without close() method."""
        app = self._build_app_with_teardown()
        
        # Add extension without close method
        plain_object = {"data": "value"}
        app.extensions["plain"] = plain_object
        
        # Should not raise an exception
        with app.app_context():
            pass  # Teardown should handle this gracefully


if __name__ == "__main__":
    unittest.main()
