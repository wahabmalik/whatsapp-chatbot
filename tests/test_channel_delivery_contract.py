"""
Contract tests for Story 8.2: Multi-channel Delivery Interface Preparation.

Verifies:
  AC1 – OutboundChannel interface exists with WhatsApp as the active adapter.
  AC2 – WhatsAppChannel.send() delegates to send_message() with full parity
         (retry, fallback, deferred paths are exercised through the adapter).
  AC3 – OUTBOUND_CHANNEL config is loaded with a safe 'whatsapp' default and
         validated against SUPPORTED_CHANNELS.
  AC4 – webhook flow (process_whatsapp_message) routes through the abstraction
         boundary, not via a direct call to send_message().
  AC6 – No non-WhatsApp channel credentials, endpoints, or activation paths
         are introduced.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

MINIMAL_ENV = {
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


def _make_app(extra_config: dict | None = None):
    with patch.dict(os.environ, MINIMAL_ENV, clear=False):
        from app import create_app
        app = create_app()
    if extra_config:
        app.config.update(extra_config)
    return app


# ---------------------------------------------------------------------------
# AC1 – Interface shape
# ---------------------------------------------------------------------------

class ChannelInterfaceShapeTests(unittest.TestCase):
    """OutboundChannel ABC and WhatsAppChannel adapter must satisfy the contract."""

    def test_outbound_channel_is_abstract(self):
        from app.services.channel_interface import OutboundChannel
        with self.assertRaises(TypeError):
            OutboundChannel()  # type: ignore[abstract]

    def test_whatsapp_channel_is_concrete(self):
        from app.services.channel_interface import WhatsAppChannel
        adapter = WhatsAppChannel()
        self.assertTrue(callable(adapter.send))

    def test_whatsapp_channel_in_supported_channels(self):
        from app.services.channel_interface import CHANNEL_WHATSAPP, SUPPORTED_CHANNELS
        self.assertIn(CHANNEL_WHATSAPP, SUPPORTED_CHANNELS)

    def test_get_outbound_channel_returns_whatsapp_by_default(self):
        from app.services.channel_interface import WhatsAppChannel, get_outbound_channel
        app = _make_app()
        with app.app_context():
            channel = get_outbound_channel(app)
        self.assertIsInstance(channel, WhatsAppChannel)


# ---------------------------------------------------------------------------
# AC2 – WhatsAppChannel.send delegates to send_message (behaviour parity)
# ---------------------------------------------------------------------------

class WhatsAppChannelDelegationTests(unittest.TestCase):
    """WhatsAppChannel.send must call send_message with all args forwarded."""

    def setUp(self):
        self._env = patch.dict(os.environ, MINIMAL_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_send_delegates_to_send_message(self):
        from app.services.channel_interface import WhatsAppChannel
        mock_result = {
            "ok": True,
            "status": "sent",
            "error": None,
            "fallback_sent": False,
            "operator_review_flagged": False,
            "operator_review_reason": None,
            "attempts": 1,
        }
        with patch("app.utils.whatsapp_utils.send_message", return_value=mock_result) as mock_send:
            app = _make_app()
            with app.app_context():
                channel = WhatsAppChannel()
                ctx = {"wa_id": "15551234567"}
                result = channel.send('{"to":"15551234567"}', request_id="req-abc", delivery_context=ctx)

        mock_send.assert_called_once_with(
            '{"to":"15551234567"}',
            request_id="req-abc",
            delivery_context=ctx,
        )
        self.assertEqual(result, mock_result)

    def test_send_result_shape_contains_required_keys(self):
        """Adapter result must include the keys the webhook pipeline consumes."""
        from app.services.channel_interface import WhatsAppChannel
        required_keys = {
            "ok", "status", "error", "fallback_sent",
            "operator_review_flagged", "operator_review_reason", "attempts",
        }
        sent_result = {k: None for k in required_keys}
        sent_result.update({"ok": True, "status": "sent", "attempts": 1})
        with patch("app.utils.whatsapp_utils.send_message", return_value=sent_result):
            app = _make_app()
            with app.app_context():
                channel = WhatsAppChannel()
                result = channel.send("{}", request_id="req-001")
        self.assertTrue(required_keys.issubset(result.keys()))


# ---------------------------------------------------------------------------
# AC3 – Channel-selection config loading and validation
# ---------------------------------------------------------------------------

class ChannelConfigTests(unittest.TestCase):
    """OUTBOUND_CHANNEL must be loaded from env with safe default and validated."""

    def test_default_outbound_channel_is_whatsapp(self):
        app = _make_app()
        self.assertEqual(app.config.get("OUTBOUND_CHANNEL"), "whatsapp")

    def test_explicit_whatsapp_channel_is_accepted(self):
        with patch.dict(os.environ, {**MINIMAL_ENV, "OUTBOUND_CHANNEL": "whatsapp"}):
            from app import create_app
            app = create_app()
        errors = [e for e in app.extensions.get("config_validation_errors", []) if "OUTBOUND_CHANNEL" in e]
        self.assertEqual(errors, [])

    def test_unsupported_channel_raises_validation_error(self):
        from app.config import validate_config
        app = _make_app()
        app.config["OUTBOUND_CHANNEL"] = "telegram"
        errors = validate_config(app)
        self.assertTrue(any("OUTBOUND_CHANNEL" in e for e in errors))

    def test_empty_channel_value_falls_back_gracefully(self):
        """get_outbound_channel with empty/absent OUTBOUND_CHANNEL must default to WhatsApp."""
        from app.services.channel_interface import WhatsAppChannel, get_outbound_channel
        app = _make_app()
        app.config["OUTBOUND_CHANNEL"] = ""
        with app.app_context():
            channel = get_outbound_channel(app)
        self.assertIsInstance(channel, WhatsAppChannel)

    def test_unknown_channel_raises_value_error(self):
        """get_outbound_channel with an unknown non-empty channel must raise ValueError."""
        from app.services.channel_interface import get_outbound_channel
        app = _make_app()
        app.config["OUTBOUND_CHANNEL"] = "pigeon"
        with app.app_context():
            with self.assertRaises(ValueError) as ctx:
                get_outbound_channel(app)
        self.assertIn("pigeon", str(ctx.exception))
        self.assertIn("whatsapp", str(ctx.exception))


# ---------------------------------------------------------------------------
# AC4 – Webhook flow uses abstraction boundary (not direct send_message call)
# ---------------------------------------------------------------------------

class WebhookAbstractionBoundaryTests(unittest.TestCase):
    """process_whatsapp_message must route through get_outbound_channel, not send_message."""

    def setUp(self):
        self._env = patch.dict(os.environ, MINIMAL_ENV, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _mock_delivery_result(self, status="sent"):
        return {
            "ok": True,
            "status": status,
            "error": None,
            "fallback_sent": False,
            "response_status": 200,
            "operator_review_flagged": False,
            "operator_review_reason": None,
            "attempts": 1,
        }

    def _meta_body(self, text="hello", wa_id="15551234567"):
        return {
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{"wa_id": wa_id, "profile": {"name": "Test User"}}],
                        "messages": [{"id": "msg-001", "type": "text", "text": {"body": text}, "timestamp": "1700000000"}],
                    }
                }]
            }]
        }

    def test_process_whatsapp_message_calls_get_outbound_channel(self):
        """process_whatsapp_message must invoke get_outbound_channel, not send_message directly."""
        app = _make_app()
        mock_channel = MagicMock()
        mock_channel.send.return_value = self._mock_delivery_result()

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=mock_channel) as mock_factory:
                with patch("app.utils.whatsapp_utils._generate_reply_result") as mock_ai:
                    mock_ai.return_value = {"ok": True, "reply_text": "Hi", "confidence": 0.9, "status": "ok", "error_code": None, "metadata": None}
                    from app.utils.whatsapp_utils import process_whatsapp_message
                    body = self._meta_body()
                    process_whatsapp_message(body, request_id="req-test")

        mock_factory.assert_called_once()
        mock_channel.send.assert_called_once()

    def test_process_whatsapp_message_does_not_call_send_message_directly(self):
        """send_message must NOT be called directly from process_whatsapp_message."""
        app = _make_app()
        mock_channel = MagicMock()
        mock_channel.send.return_value = self._mock_delivery_result()

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=mock_channel):
                with patch("app.utils.whatsapp_utils.send_message") as mock_direct_send:
                    with patch("app.utils.whatsapp_utils._generate_reply_result") as mock_ai:
                        mock_ai.return_value = {"ok": True, "reply_text": "Hi", "confidence": 0.9, "status": "ok", "error_code": None, "metadata": None}
                        from app.utils.whatsapp_utils import process_whatsapp_message
                        body = self._meta_body()
                        process_whatsapp_message(body, request_id="req-test2")

        mock_direct_send.assert_not_called()

    def test_delivery_result_propagated_from_channel_to_webhook_return(self):
        """Status from the channel adapter must be reflected in process_whatsapp_message output."""
        app = _make_app()
        mock_channel = MagicMock()
        mock_channel.send.return_value = self._mock_delivery_result(status="sent")

        with app.app_context():
            with patch("app.utils.whatsapp_utils.get_outbound_channel", return_value=mock_channel):
                with patch("app.utils.whatsapp_utils._generate_reply_result") as mock_ai:
                    mock_ai.return_value = {"ok": True, "reply_text": "Hi", "confidence": 0.9, "status": "ok", "error_code": None, "metadata": None}
                    from app.utils.whatsapp_utils import process_whatsapp_message
                    body = self._meta_body()
                    result = process_whatsapp_message(body, request_id="req-test3")

        self.assertEqual(result["status"], "sent")


# ---------------------------------------------------------------------------
# AC6 – Scope guard: no non-WhatsApp credentials or live activation paths
# ---------------------------------------------------------------------------

class ScopeGuardTests(unittest.TestCase):
    """Verify no production non-WhatsApp channel config was introduced."""

    def test_supported_channels_only_contains_whatsapp(self):
        """SUPPORTED_CHANNELS must remain WhatsApp-only for Story 8.2."""
        from app.services.channel_interface import SUPPORTED_CHANNELS
        self.assertEqual(list(SUPPORTED_CHANNELS), ["whatsapp"])

    def test_registry_only_contains_whatsapp(self):
        """_CHANNEL_REGISTRY must not have any non-stub live channel registered."""
        from app.services.channel_interface import _CHANNEL_REGISTRY, WhatsAppChannel
        self.assertEqual(set(_CHANNEL_REGISTRY.keys()), {"whatsapp"})
        self.assertIs(_CHANNEL_REGISTRY["whatsapp"], WhatsAppChannel)


if __name__ == "__main__":
    unittest.main()
