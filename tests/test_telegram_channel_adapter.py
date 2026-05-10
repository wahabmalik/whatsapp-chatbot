"""
Contract tests for Story 9.2: Production Adapter Delivery (Single Non-WhatsApp Channel).

Verifies:
  AC 9.2.1 — TelegramChannel is wired behind OutboundChannel without touching WhatsApp logic.
  AC 9.2.2 — Missing credentials → disabled state (no crash); error result returned.
  AC 9.2.3 — Routing is config-driven (OUTBOUND_CHANNEL=telegram); delivery_context
              override respected; no silent channel fallback.
  AC 9.2.4 — Log entries include provider=telegram, correlation_id, outcome; no token logged.
  AC 9.2.5 — Same retry/fallback contract as WhatsApp: 4 attempts (1+3 at 1s/2s/4s),
              then 2-attempt fallback text.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, call, patch

import requests

from app.services.telegram_channel import (
    CHANNEL_KEY,
    TelegramChannel,
    _RETRY_BACKOFF,
    _extract_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(
    bot_token: str = "test-token",
    default_chat_id: str = "test-chat-id",
    send_timeout: float = 5.0,
    fallback_text: str = "Delays. Follow-up soon.",
    fallback_max_retries: int = 2,
) -> TelegramChannel:
    return TelegramChannel(
        bot_token=bot_token,
        default_chat_id=default_chat_id,
        send_timeout=send_timeout,
        fallback_text=fallback_text,
        fallback_max_retries=fallback_max_retries,
    )


def _make_whatsapp_payload(text: str = "Hello from bot") -> str:
    return json.dumps({"messaging_product": "whatsapp", "to": "15551234", "text": {"body": text}})


def _mock_ok_response(status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.return_value = None
    return resp


def _mock_error_response(status_code: int = 500) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = requests.HTTPError(
        response=resp, request=MagicMock()
    )
    return resp


# ---------------------------------------------------------------------------
# AC 9.2.1 — Interface contract
# ---------------------------------------------------------------------------

class TelegramChannelInterfaceTests(unittest.TestCase):
    """TelegramChannel must satisfy OutboundChannel contract (AC 9.2.1)."""

    def test_channel_key_constant(self):
        self.assertEqual(CHANNEL_KEY, "telegram")

    def test_telegram_channel_is_subclass_of_outbound_channel(self):
        from app.services.channel_interface import OutboundChannel
        self.assertTrue(issubclass(TelegramChannel, OutboundChannel))

    def test_telegram_channel_is_concrete(self):
        adapter = _make_adapter()
        self.assertTrue(callable(adapter.send))

    def test_send_result_shape_on_success(self):
        adapter = _make_adapter()
        with patch("requests.post", return_value=_mock_ok_response()):
            result = adapter.send(
                _make_whatsapp_payload(), request_id="req-shape-test"
            )
        required_keys = {
            "ok", "status", "error", "fallback_sent",
            "operator_review_flagged", "operator_review_reason",
            "attempts", "response_status",
        }
        self.assertTrue(required_keys.issubset(result.keys()))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertFalse(result["fallback_sent"])
        self.assertFalse(result["operator_review_flagged"])

    def test_whatsapp_channel_unmodified(self):
        """WhatsApp routing logic must not be touched (AC 9.2.1)."""
        from app.services.channel_interface import WhatsAppChannel
        adapter = WhatsAppChannel()
        with patch("app.utils.whatsapp_utils.send_message") as mock_send:
            mock_send.return_value = {"ok": True, "status": "sent"}
            result = adapter.send("data", request_id="r1")
        mock_send.assert_called_once()
        self.assertEqual(result["ok"], True)


# ---------------------------------------------------------------------------
# AC 9.2.2 — Disabled state (missing credentials)
# ---------------------------------------------------------------------------

class TelegramDisabledStateTests(unittest.TestCase):
    """Missing credentials → adapter disabled, no crash (AC 9.2.2)."""

    def test_disabled_when_token_absent(self):
        adapter = TelegramChannel(bot_token=None, default_chat_id="chat-123")
        self.assertFalse(adapter._enabled)

    def test_disabled_when_chat_id_absent(self):
        adapter = TelegramChannel(bot_token="token-abc", default_chat_id=None)
        self.assertFalse(adapter._enabled)

    def test_disabled_when_both_absent(self):
        adapter = TelegramChannel(bot_token=None, default_chat_id=None)
        self.assertFalse(adapter._enabled)

    def test_enabled_when_both_present(self):
        adapter = _make_adapter()
        self.assertTrue(adapter._enabled)

    def test_disabled_send_returns_error_dict_not_exception(self):
        adapter = TelegramChannel(bot_token=None, default_chat_id=None)
        result = adapter.send(_make_whatsapp_payload(), request_id="req-disabled")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "telegram_adapter_disabled")
        self.assertEqual(result["attempts"], 0)
        self.assertTrue(result["operator_review_flagged"])

    def test_disabled_send_does_not_call_requests(self):
        adapter = TelegramChannel(bot_token=None, default_chat_id=None)
        with patch("requests.post") as mock_post:
            adapter.send(_make_whatsapp_payload(), request_id="req-no-http")
        mock_post.assert_not_called()

    def test_from_app_with_missing_credentials_creates_disabled_adapter(self):
        app = MagicMock()
        app.config = {
            "TELEGRAM_BOT_TOKEN": None,
            "TELEGRAM_DEFAULT_CHAT_ID": None,
            "TELEGRAM_SEND_TIMEOUT_SECONDS": 10.0,
            "OUTBOUND_FALLBACK_TEXT": "Delays.",
            "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
        }
        adapter = TelegramChannel.from_app(app)
        self.assertFalse(adapter._enabled)

    def test_from_app_with_valid_credentials_creates_enabled_adapter(self):
        app = MagicMock()
        app.config = {
            "TELEGRAM_BOT_TOKEN": "bot-token-123",
            "TELEGRAM_DEFAULT_CHAT_ID": "chat-456",
            "TELEGRAM_SEND_TIMEOUT_SECONDS": 10.0,
            "OUTBOUND_FALLBACK_TEXT": "Delays.",
            "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
        }
        adapter = TelegramChannel.from_app(app)
        self.assertTrue(adapter._enabled)


# ---------------------------------------------------------------------------
# AC 9.2.3 — Config-driven routing
# ---------------------------------------------------------------------------

class TelegramRoutingTests(unittest.TestCase):
    """Routing is explicit and config-driven (AC 9.2.3)."""

    def test_uses_default_chat_id_from_config(self):
        adapter = _make_adapter(default_chat_id="default-chat")
        captured = {}
        def mock_post(url, json=None, timeout=None):
            captured["payload"] = json
            return _mock_ok_response()

        with patch("requests.post", side_effect=mock_post):
            adapter.send(_make_whatsapp_payload(), request_id="req-routing")

        self.assertEqual(captured["payload"]["chat_id"], "default-chat")

    def test_delivery_context_overrides_default_chat_id(self):
        adapter = _make_adapter(default_chat_id="default-chat")
        captured = {}
        def mock_post(url, json=None, timeout=None):
            captured["payload"] = json
            return _mock_ok_response()

        with patch("requests.post", side_effect=mock_post):
            adapter.send(
                _make_whatsapp_payload(),
                request_id="req-override",
                delivery_context={"telegram_chat_id": "override-chat"},
            )

        self.assertEqual(captured["payload"]["chat_id"], "override-chat")

    def test_non_dict_delivery_context_falls_back_to_default_chat_id(self):
        adapter = _make_adapter(default_chat_id="default-chat")
        captured = {}

        def mock_post(url, json=None, timeout=None):
            captured["payload"] = json
            return _mock_ok_response()

        with patch("requests.post", side_effect=mock_post):
            adapter.send(
                _make_whatsapp_payload(),
                request_id="req-non-dict-context",
                delivery_context=["invalid-context"],
            )

        self.assertEqual(captured["payload"]["chat_id"], "default-chat")

    def test_get_outbound_channel_returns_telegram_for_telegram_config(self):
        """get_outbound_channel() must return TelegramChannel when OUTBOUND_CHANNEL=telegram."""
        import os
        from unittest.mock import patch as p
        from app.services.channel_interface import get_outbound_channel

        app = MagicMock()
        app.config = {
            "OUTBOUND_CHANNEL": "telegram",
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_DEFAULT_CHAT_ID": "chat",
            "TELEGRAM_SEND_TIMEOUT_SECONDS": 10.0,
            "OUTBOUND_FALLBACK_TEXT": "Delays.",
            "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
        }
        channel = get_outbound_channel(app)
        self.assertIsInstance(channel, TelegramChannel)


# ---------------------------------------------------------------------------
# AC 9.2.4 — Log field contract (provider, correlation_id, outcome; no token)
# ---------------------------------------------------------------------------

class TelegramLogFieldContractTests(unittest.TestCase):
    """Log entries must include provider, correlation_id, outcome; no token (AC 9.2.4)."""

    def test_send_logs_provider_telegram(self):
        adapter = _make_adapter()
        with patch("requests.post", return_value=_mock_ok_response()):
            with self.assertLogs("app.services.telegram_channel", level="INFO") as cm:
                adapter.send(_make_whatsapp_payload(), request_id="req-log-test")

        combined = " ".join(cm.output)
        self.assertIn("provider=telegram", combined)
        self.assertIn("outcome=attempt", combined)
        self.assertIn("outcome=success", combined)

    def test_send_logs_correlation_id(self):
        adapter = _make_adapter()
        with patch("requests.post", return_value=_mock_ok_response()):
            with patch("app.services.telegram_channel.get_correlation_id", return_value="corr-abc"):
                with self.assertLogs("app.services.telegram_channel", level="INFO") as cm:
                    adapter.send(_make_whatsapp_payload(), request_id="req-corr")

        combined = " ".join(cm.output)
        self.assertIn("corr-abc", combined)

    def test_send_does_not_log_token_value(self):
        adapter = TelegramChannel(
            bot_token="my-secret-bot-token-12345",
            default_chat_id="chat-123",
        )
        with patch("requests.post", return_value=_mock_ok_response()):
            with self.assertLogs("app.services.telegram_channel", level="INFO") as cm:
                adapter.send(_make_whatsapp_payload(), request_id="req-no-cred-leak")

        combined = " ".join(cm.output)
        self.assertNotIn("my-secret-bot-token-12345", combined)

    def test_disabled_adapter_logs_provider_not_token(self):
        with self.assertLogs("app.services.telegram_channel", level="WARNING") as cm:
            TelegramChannel(bot_token=None, default_chat_id=None)

        combined = " ".join(cm.output)
        self.assertIn("provider=telegram", combined)
        self.assertNotIn("None", combined)

    def test_disabled_send_logs_outcome_disabled(self):
        adapter = TelegramChannel(bot_token=None, default_chat_id=None)

        with self.assertLogs("app.services.telegram_channel", level="ERROR") as cm:
            adapter.send(_make_whatsapp_payload(), request_id="req-disabled-log")

        combined = " ".join(cm.output)
        self.assertIn("outcome=disabled", combined)

    def test_request_exception_logs_error_type_not_token(self):
        adapter = TelegramChannel(
            bot_token="123456:ABC-DEF1234-SECRET",
            default_chat_id="chat-123",
        )
        exception_text = (
            "500 Server Error: Internal Server Error for url: "
            "https://api.telegram.org/bot123456:ABC-DEF1234-SECRET/sendMessage"
        )

        with patch("requests.post", side_effect=requests.RequestException(exception_text)):
            with self.assertLogs("app.services.telegram_channel", level="ERROR") as cm:
                with patch("time.sleep"):
                    adapter.send(_make_whatsapp_payload(), request_id="req-exc-log")

        combined = " ".join(cm.output)
        self.assertIn("error_type=RequestException", combined)
        self.assertNotIn("ABC-DEF1234-SECRET", combined)
        self.assertNotIn("/bot123456:", combined)


# ---------------------------------------------------------------------------
# AC 9.2.5 — Retry / fallback contract
# ---------------------------------------------------------------------------

class TelegramRetryContractTests(unittest.TestCase):
    """Retry schedule and fallback semantics must match WhatsApp path (AC 9.2.5)."""

    def test_retry_backoff_schedule_matches_whatsapp(self):
        """_RETRY_BACKOFF must be (1, 2, 4) — same as _retry_backoff_schedule()."""
        self.assertEqual(_RETRY_BACKOFF, (1, 2, 4))

    def test_success_on_first_attempt_returns_attempts_1(self):
        adapter = _make_adapter()
        with patch("requests.post", return_value=_mock_ok_response()):
            result = adapter.send(_make_whatsapp_payload(), request_id="req-first")
        self.assertEqual(result["attempts"], 1)

    def test_success_on_second_attempt(self):
        adapter = _make_adapter()
        responses = [requests.ConnectionError("fail"), _mock_ok_response()]
        call_count = {"n": 0}

        def mock_post(*args, **kwargs):
            i = call_count["n"]
            call_count["n"] += 1
            r = responses[i]
            if isinstance(r, Exception):
                raise r
            return r

        with patch("requests.post", side_effect=mock_post):
            with patch("time.sleep"):
                result = adapter.send(_make_whatsapp_payload(), request_id="req-retry")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["attempts"], 2)

    def test_all_four_attempts_made_before_fallback(self):
        adapter = _make_adapter(fallback_max_retries=1)
        post_calls = []

        def mock_post(url, json=None, timeout=None):
            post_calls.append(url)
            raise requests.ConnectionError("always fail")

        with patch("requests.post", side_effect=mock_post):
            with patch("time.sleep"):
                result = adapter.send(_make_whatsapp_payload(), request_id="req-exhaust")

        # 4 primary attempts + up to 1 fallback attempt = at most 5 total calls
        # The fallback also uses requests.post
        self.assertEqual(len(post_calls), 4 + 1)  # 4 primary + 1 fallback
        self.assertFalse(result["ok"])
        # attempts counter reflects primary attempts only
        self.assertEqual(result["attempts"], len(_RETRY_BACKOFF) + 1)

    def test_retry_uses_correct_backoff_intervals(self):
        adapter = _make_adapter()
        sleep_calls = []

        def mock_post(*args, **kwargs):
            raise requests.ConnectionError("fail")

        with patch("requests.post", side_effect=mock_post):
            with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
                adapter.send(_make_whatsapp_payload(), request_id="req-backoff")

        # First attempt has no sleep; retries 1,2,3 sleep at 1s, 2s, 4s
        self.assertEqual(sleep_calls[:3], [1, 2, 4])

    def test_fallback_sent_when_primary_exhausted(self):
        adapter = _make_adapter(fallback_max_retries=2)
        call_count = {"n": 0}

        def mock_post(url, json=None, timeout=None):
            call_count["n"] += 1
            if call_count["n"] <= 4:
                # Primary attempts all fail
                raise requests.ConnectionError("primary fail")
            # Fallback succeeds on first attempt
            return _mock_ok_response()

        with patch("requests.post", side_effect=mock_post):
            with patch("time.sleep"):
                result = adapter.send(_make_whatsapp_payload(), request_id="req-fallback")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "fallback_sent")
        self.assertTrue(result["fallback_sent"])
        self.assertTrue(result["operator_review_flagged"])

    def test_error_result_when_fallback_also_exhausted(self):
        adapter = _make_adapter(fallback_max_retries=2)

        with patch("requests.post", side_effect=requests.ConnectionError("always fail")):
            with patch("time.sleep"):
                result = adapter.send(_make_whatsapp_payload(), request_id="req-total-fail")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["fallback_sent"])
        self.assertEqual(result["error"], "all_attempts_exhausted")
        self.assertTrue(result["operator_review_flagged"])

    def test_timeout_treated_as_recoverable(self):
        adapter = _make_adapter()
        call_count = {"n": 0}

        def mock_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise requests.Timeout("timed out")
            return _mock_ok_response()

        with patch("requests.post", side_effect=mock_post):
            with patch("time.sleep"):
                result = adapter.send(_make_whatsapp_payload(), request_id="req-timeout")

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)


# ---------------------------------------------------------------------------
# _extract_text helper
# ---------------------------------------------------------------------------

class ExtractTextTests(unittest.TestCase):
    """_extract_text parses WhatsApp-format JSON to plain text."""

    def test_extracts_text_body(self):
        payload = json.dumps({"text": {"body": "Hello!"}})
        self.assertEqual(_extract_text(payload), "Hello!")

    def test_falls_back_to_raw_on_invalid_json(self):
        raw = "not json"
        self.assertEqual(_extract_text(raw), raw)

    def test_falls_back_to_raw_when_text_key_absent(self):
        payload = json.dumps({"other": "data"})
        result = _extract_text(payload)
        # No text key → returns original data string
        self.assertEqual(result, payload)

    def test_handles_non_dict_text_value(self):
        payload = json.dumps({"text": "plain string"})
        result = _extract_text(payload)
        self.assertEqual(result, "plain string")


if __name__ == "__main__":
    unittest.main()
