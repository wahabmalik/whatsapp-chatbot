from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.channel_interface import get_outbound_channel
from app.services.social_bridge_channel import (
    InstagramChannel,
    MessengerChannel,
    TikTokChannel,
)


def _mock_ok_response(status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.return_value = None
    return response


@pytest.mark.parametrize(
    ("channel_name", "channel_cls", "config"),
    [
        (
            "instagram",
            InstagramChannel,
            {
                "INSTAGRAM_OUTBOUND_URL": "https://example.com/instagram",
                "INSTAGRAM_ACCESS_TOKEN": "token-1",
                "INSTAGRAM_DEFAULT_RECIPIENT_ID": "ig-user-1",
                "INSTAGRAM_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
        (
            "messenger",
            MessengerChannel,
            {
                "MESSENGER_OUTBOUND_URL": "https://example.com/messenger",
                "MESSENGER_PAGE_ACCESS_TOKEN": "token-2",
                "MESSENGER_DEFAULT_RECIPIENT_ID": "psid-1",
                "MESSENGER_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
        (
            "tiktok",
            TikTokChannel,
            {
                "TIKTOK_OUTBOUND_URL": "https://example.com/tiktok",
                "TIKTOK_ACCESS_TOKEN": "token-3",
                "TIKTOK_DEFAULT_RECIPIENT_ID": "tt-user-1",
                "TIKTOK_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
    ],
)
def test_get_outbound_channel_returns_expected_social_adapter(
    channel_name: str,
    channel_cls,
    config: dict[str, object],
):
    app = MagicMock()
    app.config = {"OUTBOUND_CHANNEL": channel_name, **config}

    channel = get_outbound_channel(app)

    assert isinstance(channel, channel_cls)


@pytest.mark.parametrize(
    ("channel_cls", "kwargs", "expected_error"),
    [
        (
            InstagramChannel,
            {"outbound_url": None, "default_recipient_id": "ig-user-1", "access_token": "token"},
            "instagram_adapter_disabled",
        ),
        (
            MessengerChannel,
            {"outbound_url": "https://example.com/messenger", "default_recipient_id": None, "access_token": "token"},
            "messenger_adapter_disabled",
        ),
        (
            TikTokChannel,
            {"outbound_url": None, "default_recipient_id": None, "access_token": "token"},
            "tiktok_adapter_disabled",
        ),
    ],
)
def test_disabled_social_adapter_returns_contract_error(channel_cls, kwargs, expected_error: str):
    channel = channel_cls(**kwargs)

    result = channel.send('{"text": {"body": "hello"}}', request_id="req-disabled")

    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["attempts"] == 0


@pytest.mark.parametrize(
    ("channel_cls", "kwargs", "override_key"),
    [
        (
            InstagramChannel,
            {"outbound_url": "https://example.com/instagram", "default_recipient_id": "ig-default", "access_token": "token"},
            "instagram_recipient_id",
        ),
        (
            MessengerChannel,
            {"outbound_url": "https://example.com/messenger", "default_recipient_id": "msg-default", "access_token": "token"},
            "messenger_recipient_id",
        ),
        (
            TikTokChannel,
            {"outbound_url": "https://example.com/tiktok", "default_recipient_id": "tt-default", "access_token": "token"},
            "tiktok_recipient_id",
        ),
    ],
)
def test_social_adapter_uses_recipient_override_and_bearer_auth(
    channel_cls,
    kwargs: dict[str, str],
    override_key: str,
):
    channel = channel_cls(**kwargs)
    captured: dict[str, object] = {}

    def _mock_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _mock_ok_response()

    with patch("requests.post", side_effect=_mock_post):
        result = channel.send(
            '{"text": {"body": "hello bridge"}}',
            request_id="req-override",
            delivery_context={override_key: "override-user-1"},
        )

    assert result["ok"] is True
    assert captured["json"]["recipient"]["id"] == "override-user-1"
    assert captured["headers"]["Authorization"] == "Bearer token"