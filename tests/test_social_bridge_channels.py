from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.channel_interface import get_outbound_channel
from app.services.social_bridge_channel import (
    DiscordChannel,
    InstagramChannel,
    LineChannel,
    MessengerChannel,
    SlackChannel,
    SmsChannel,
    TeamsChannel,
    TikTokChannel,
    ViberChannel,
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
        (
            "discord",
            DiscordChannel,
            {
                "DISCORD_OUTBOUND_URL": "https://example.com/discord",
                "DISCORD_BOT_TOKEN": "token-discord",
                "DISCORD_DEFAULT_RECIPIENT_ID": "discord-channel-1",
                "DISCORD_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
        (
            "slack",
            SlackChannel,
            {
                "SLACK_OUTBOUND_URL": "https://example.com/slack",
                "SLACK_BOT_TOKEN": "token-slack",
                "SLACK_DEFAULT_RECIPIENT_ID": "C012345",
                "SLACK_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
        (
            "teams",
            TeamsChannel,
            {
                "TEAMS_OUTBOUND_URL": "https://example.com/teams",
                "TEAMS_ACCESS_TOKEN": "token-teams",
                "TEAMS_DEFAULT_RECIPIENT_ID": "teams-user-1",
                "TEAMS_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
        (
            "sms",
            SmsChannel,
            {
                "SMS_OUTBOUND_URL": "https://example.com/sms",
                "SMS_API_KEY": "token-sms",
                "SMS_DEFAULT_RECIPIENT_ID": "+15551234567",
                "SMS_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
        (
            "line",
            LineChannel,
            {
                "LINE_OUTBOUND_URL": "https://example.com/line",
                "LINE_CHANNEL_ACCESS_TOKEN": "token-line",
                "LINE_DEFAULT_RECIPIENT_ID": "line-user-1",
                "LINE_SEND_TIMEOUT_SECONDS": 10.0,
                "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
            },
        ),
        (
            "viber",
            ViberChannel,
            {
                "VIBER_OUTBOUND_URL": "https://example.com/viber",
                "VIBER_AUTH_TOKEN": "token-viber",
                "VIBER_DEFAULT_RECIPIENT_ID": "viber-user-1",
                "VIBER_SEND_TIMEOUT_SECONDS": 10.0,
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
        (
            DiscordChannel,
            {"outbound_url": None, "default_recipient_id": "discord-1", "access_token": "token"},
            "discord_adapter_disabled",
        ),
        (
            SlackChannel,
            {"outbound_url": "https://example.com/slack", "default_recipient_id": None, "access_token": "token"},
            "slack_adapter_disabled",
        ),
        (
            SmsChannel,
            {"outbound_url": None, "default_recipient_id": None, "access_token": "token"},
            "sms_adapter_disabled",
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
        (
            DiscordChannel,
            {"outbound_url": "https://example.com/discord", "default_recipient_id": "discord-default", "access_token": "token"},
            "discord_recipient_id",
        ),
        (
            SlackChannel,
            {"outbound_url": "https://example.com/slack", "default_recipient_id": "slack-default", "access_token": "token"},
            "slack_recipient_id",
        ),
        (
            TeamsChannel,
            {"outbound_url": "https://example.com/teams", "default_recipient_id": "teams-default", "access_token": "token"},
            "teams_recipient_id",
        ),
        (
            SmsChannel,
            {"outbound_url": "https://example.com/sms", "default_recipient_id": "sms-default", "access_token": "token"},
            "sms_recipient_id",
        ),
        (
            LineChannel,
            {"outbound_url": "https://example.com/line", "default_recipient_id": "line-default", "access_token": "token"},
            "line_recipient_id",
        ),
        (
            ViberChannel,
            {"outbound_url": "https://example.com/viber", "default_recipient_id": "viber-default", "access_token": "token"},
            "viber_recipient_id",
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
