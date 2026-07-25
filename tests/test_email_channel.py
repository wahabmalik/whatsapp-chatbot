from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.channel_interface import get_outbound_channel
from app.services.email_channel import EmailChannel


def test_get_outbound_channel_returns_email_adapter():
    app = MagicMock()
    app.config = {
        "OUTBOUND_CHANNEL": "email",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": 587,
        "SMTP_USERNAME": "bot@example.com",
        "SMTP_PASSWORD": "secret",
        "SMTP_FROM_ADDRESS": "bot@example.com",
        "SMTP_USE_TLS": True,
        "EMAIL_DEFAULT_RECIPIENT": "customer@example.com",
        "EMAIL_SUBJECT_PREFIX": "Support",
        "EMAIL_SEND_TIMEOUT_SECONDS": 10.0,
        "WHATSAPP_FALLBACK_MAX_RETRIES": 2,
    }

    channel = get_outbound_channel(app)

    assert isinstance(channel, EmailChannel)
    assert channel._enabled is True  # noqa: SLF001


def test_disabled_email_adapter_returns_contract_error():
    channel = EmailChannel(
        smtp_host=None,
        from_address="bot@example.com",
        default_recipient="customer@example.com",
    )

    result = channel.send('{"text": {"body": "hello"}}', request_id="req-disabled")

    assert result["ok"] is False
    assert result["error"] == "email_adapter_disabled"
    assert result["attempts"] == 0


def test_email_adapter_sends_via_smtp_and_honors_recipient_override():
    channel = EmailChannel(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username="bot@example.com",
        smtp_password="secret",
        from_address="bot@example.com",
        default_recipient="default@example.com",
        use_tls=True,
    )
    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return None

        def starttls(self, context=None):
            captured["starttls"] = True

        def login(self, username, password):
            captured["login"] = (username, password)

        def sendmail(self, from_addr, to_addrs, msg):
            captured["from_addr"] = from_addr
            captured["to_addrs"] = to_addrs
            captured["msg"] = msg

    with patch("app.services.email_channel.smtplib.SMTP", _FakeSMTP):
        result = channel.send(
            '{"text": {"body": "hello email"}}',
            request_id="req-email-1",
            delivery_context={"email_recipient": "override@example.com"},
        )

    assert result["ok"] is True
    assert result["status"] == "sent"
    assert captured["to_addrs"] == ["override@example.com"]
    assert captured["from_addr"] == "bot@example.com"
    # MIMEText may encode the body as base64 depending on content/charset.
    assert "To: override@example.com" in str(captured["msg"])
    assert "Subject: Support [req-email-1]" in str(captured["msg"])
