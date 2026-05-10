"""Shared outbound adapter parity suite (Story 9.3).

This suite validates behavior parity between the WhatsApp baseline adapter and
non-WhatsApp adapters across core outbound contract scenarios.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.channel_interface import WhatsAppChannel
from app.services.social_bridge_channel import (
    InstagramChannel,
    MessengerChannel,
    TikTokChannel,
)
from app.services.telegram_channel import TelegramChannel


ALL_ADAPTERS = ["whatsapp", "telegram", "instagram", "messenger", "tiktok"]


def _required_contract_keys() -> set[str]:
    return {
        "ok",
        "status",
        "error",
        "fallback_sent",
        "operator_review_flagged",
        "operator_review_reason",
        "attempts",
    }


def _mock_ok_response(status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.return_value = None
    return response


def _telegram_payload(text: str = "hello parity") -> str:
    return json.dumps({"messaging_product": "whatsapp", "text": {"body": text}})


def _make_http_adapter(adapter_name: str):
    if adapter_name == "telegram":
        return TelegramChannel(bot_token="token", default_chat_id="chat")

    social_adapters = {
        "instagram": InstagramChannel,
        "messenger": MessengerChannel,
        "tiktok": TikTokChannel,
    }
    return social_adapters[adapter_name](
        outbound_url=f"https://example.com/{adapter_name}",
        default_recipient_id="recipient-123",
        access_token="token-123",
    )


@pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
def test_success_path_contract_parity(adapter_name: str):
    """AC 9.3.1: success path is contract-compatible for all adapters."""
    if adapter_name == "whatsapp":
        adapter = WhatsAppChannel()
        expected = {
            "ok": True,
            "status": "sent",
            "error": None,
            "fallback_sent": False,
            "operator_review_flagged": False,
            "operator_review_reason": None,
            "attempts": 1,
            "response_status": 200,
        }
        with patch("app.utils.whatsapp_utils.send_message", return_value=expected):
            result = adapter.send("{}", request_id="req-parity-success")
    else:
        adapter = _make_http_adapter(adapter_name)
        with patch("requests.post", return_value=_mock_ok_response()):
            result = adapter.send(_telegram_payload(), request_id="req-parity-success")

    assert _required_contract_keys().issubset(result.keys())
    assert result["ok"] is True
    assert result["status"] == "sent"
    assert result["attempts"] >= 1


@pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
def test_retry_path_parity(adapter_name: str):
    """AC 9.3.1: retry path is exercised and reported for all adapters."""
    if adapter_name == "whatsapp":
        adapter = WhatsAppChannel()
        retried = {
            "ok": True,
            "status": "sent",
            "error": None,
            "fallback_sent": False,
            "operator_review_flagged": False,
            "operator_review_reason": None,
            "attempts": 2,
            "response_status": 200,
        }
        with patch("app.utils.whatsapp_utils.send_message", return_value=retried):
            result = adapter.send("{}", request_id="req-parity-retry")
    else:
        adapter = _make_http_adapter(adapter_name)
        calls: dict[str, int] = {"n": 0}

        def post_once_then_ok(*args: Any, **kwargs: Any):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.ConnectionError("transient")
            return _mock_ok_response()

        with patch("requests.post", side_effect=post_once_then_ok):
            with patch("time.sleep"):
                result = adapter.send(_telegram_payload(), request_id="req-parity-retry")

    assert result["ok"] is True
    assert result["status"] == "sent"
    assert result["attempts"] >= 2


@pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
def test_retry_exhaustion_fallback_parity(adapter_name: str):
    """AC 9.3.1: exhaustion yields operator-review fallback semantics for all adapters."""
    if adapter_name == "whatsapp":
        adapter = WhatsAppChannel()
        exhausted = {
            "ok": False,
            "status": "fallback_sent",
            "error": None,
            "fallback_sent": True,
            "operator_review_flagged": True,
            "operator_review_reason": "primary_exhausted_fallback_sent",
            "attempts": 4,
            "response_status": None,
        }
        with patch("app.utils.whatsapp_utils.send_message", return_value=exhausted):
            result = adapter.send("{}", request_id="req-parity-exhausted")
    else:
        adapter = _make_http_adapter(adapter_name)
        calls: dict[str, int] = {"n": 0}

        def fail_then_fallback_ok(*args: Any, **kwargs: Any):
            calls["n"] += 1
            if calls["n"] <= 4:
                raise requests.ConnectionError("primary failure")
            return _mock_ok_response()

        with patch("requests.post", side_effect=fail_then_fallback_ok):
            with patch("time.sleep"):
                result = adapter.send(_telegram_payload(), request_id="req-parity-exhausted")

    assert result["ok"] is False
    assert result["fallback_sent"] is True
    assert result["operator_review_flagged"] is True
    assert result["status"] in {"fallback_sent", "error"}


@pytest.mark.parametrize("adapter_name", ALL_ADAPTERS)
def test_correlation_and_observability_parity(adapter_name: str):
    """AC 9.3.1: request correlation and observability fields are present for all adapters."""
    request_id = "req-parity-correlation"

    if adapter_name == "whatsapp":
        adapter = WhatsAppChannel()
        mock_result = {
            "ok": True,
            "status": "sent",
            "error": None,
            "fallback_sent": False,
            "operator_review_flagged": False,
            "operator_review_reason": None,
            "attempts": 1,
            "response_status": 200,
        }
        with patch("app.utils.whatsapp_utils.send_message", return_value=mock_result) as mock_send:
            result = adapter.send(
                "{}",
                request_id=request_id,
                delivery_context={"wa_id": "15551234567"},
            )
        assert mock_send.call_args.kwargs["request_id"] == request_id
        assert isinstance(mock_send.call_args.kwargs["delivery_context"], dict)
    elif adapter_name == "telegram":
        adapter = _make_http_adapter(adapter_name)
        with patch("app.services.telegram_channel.get_correlation_id", return_value="corr-parity"):
            with patch("requests.post", return_value=_mock_ok_response()):
                with patch("app.services.telegram_channel.logger.info") as log_info:
                    result = adapter.send(_telegram_payload(), request_id=request_id)
        emitted = " ".join(str(call.args[0]) for call in log_info.call_args_list)
        emitted_args = " ".join(
            " ".join(str(arg) for arg in call.args[1:]) for call in log_info.call_args_list
        )
        assert "provider=telegram" in emitted
        assert "correlation_id=%s" in emitted
        assert "corr-parity" in emitted_args
    else:
        adapter = _make_http_adapter(adapter_name)
        with patch("app.services.social_bridge_channel.get_correlation_id", return_value="corr-parity"):
            with patch("requests.post", return_value=_mock_ok_response()):
                with patch("app.services.social_bridge_channel.logger.info") as log_info:
                    result = adapter.send(_telegram_payload(), request_id=request_id)
        emitted = " ".join(str(call.args[0]) for call in log_info.call_args_list)
        emitted_args = " ".join(
            " ".join(str(arg) for arg in call.args[1:]) for call in log_info.call_args_list
        )
        assert "provider=%s" in emitted
        assert "correlation_id=%s" in emitted
        assert adapter_name in emitted_args
        assert "corr-parity" in emitted_args

    assert _required_contract_keys().issubset(result.keys())
    assert "status" in result


def test_mixed_channel_staging_gate_c_evidence_present():
    """AC 9.3.3: Gate C evidence artifact exists and records >=1000 / >=99.0% thresholds."""
    from pathlib import Path

    artifact = Path("_bmad-output/test-artifacts/story-9-3-mixed-channel-staging-gate-c.md")
    assert artifact.exists(), "Missing Story 9.3 Gate C evidence artifact"

    text = artifact.read_text(encoding="utf-8")
    assert "1000" in text
    assert "99.0%" in text
