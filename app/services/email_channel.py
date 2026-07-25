"""Email / Gmail outbound adapter for support-inbox replies.

Uses SMTP (including Gmail SMTP when configured) behind the OutboundChannel
interface. Activate with OUTBOUND_CHANNEL=email.

Required config:
    SMTP_HOST
    SMTP_FROM_ADDRESS (or SMTP_USERNAME)
    EMAIL_DEFAULT_RECIPIENT

Optional:
    SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_USE_TLS
    EMAIL_SUBJECT_PREFIX
    EMAIL_SEND_TIMEOUT_SECONDS
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from typing import Any

from app.services.channel_interface import OutboundChannel
from app.services.observability import get_correlation_id

logger = logging.getLogger(__name__)

CHANNEL_KEY = "email"

_RETRY_BACKOFF: tuple[int, ...] = (1, 2, 4)
_DEFAULT_FALLBACK_TEXT = (
    "We're experiencing delays right now. A human agent will follow up shortly."
)
_DEFAULT_FALLBACK_MAX_RETRIES = 2
_DEFAULT_SUBJECT_PREFIX = "Support"


def _extract_text(data: str) -> str:
    try:
        payload = json.loads(data)
        body = payload.get("text", {})
        if isinstance(body, dict):
            return str(body.get("body") or data)
        return str(body) if body else data
    except (json.JSONDecodeError, AttributeError, TypeError):
        return data


class EmailChannel(OutboundChannel):
    """SMTP outbound adapter for support-inbox style replies."""

    def __init__(
        self,
        *,
        smtp_host: str | None,
        smtp_port: int = 587,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        default_recipient: str | None = None,
        use_tls: bool = True,
        subject_prefix: str = _DEFAULT_SUBJECT_PREFIX,
        send_timeout: float = 10.0,
        fallback_text: str = _DEFAULT_FALLBACK_TEXT,
        fallback_max_retries: int = _DEFAULT_FALLBACK_MAX_RETRIES,
    ) -> None:
        self._smtp_host = (smtp_host or "").strip()
        self._smtp_port = int(smtp_port or 587)
        self._smtp_username = (smtp_username or "").strip()
        self._smtp_password = (smtp_password or "").strip()
        self._from_address = (from_address or self._smtp_username or "").strip()
        self._default_recipient = (default_recipient or "").strip()
        self._use_tls = bool(use_tls)
        self._subject_prefix = (subject_prefix or _DEFAULT_SUBJECT_PREFIX).strip()
        self._send_timeout = max(0.1, float(send_timeout))
        self._fallback_text = (fallback_text or _DEFAULT_FALLBACK_TEXT).strip()
        self._fallback_max_retries = max(1, int(fallback_max_retries))
        self._enabled = bool(self._smtp_host and self._from_address and self._default_recipient)

        if not self._enabled:
            logger.warning(
                "provider=email status=disabled reason=missing_configuration "
                "smtp_host=%s from_address=%s default_recipient=%s",
                "set" if self._smtp_host else "missing",
                "set" if self._from_address else "missing",
                "set" if self._default_recipient else "missing",
            )

    @classmethod
    def from_app(cls, app) -> "EmailChannel":
        return cls(
            smtp_host=app.config.get("SMTP_HOST"),
            smtp_port=int(app.config.get("SMTP_PORT", 587)),
            smtp_username=app.config.get("SMTP_USERNAME"),
            smtp_password=app.config.get("SMTP_PASSWORD"),
            from_address=app.config.get("SMTP_FROM_ADDRESS") or app.config.get("SMTP_USERNAME"),
            default_recipient=app.config.get("EMAIL_DEFAULT_RECIPIENT"),
            use_tls=bool(app.config.get("SMTP_USE_TLS", True)),
            subject_prefix=str(app.config.get("EMAIL_SUBJECT_PREFIX") or _DEFAULT_SUBJECT_PREFIX),
            send_timeout=float(app.config.get("EMAIL_SEND_TIMEOUT_SECONDS", 10.0)),
            fallback_text=app.config.get("OUTBOUND_FALLBACK_TEXT", _DEFAULT_FALLBACK_TEXT),
            fallback_max_retries=int(app.config.get("WHATSAPP_FALLBACK_MAX_RETRIES", 2)),
        )

    def send(
        self,
        data: str,
        *,
        request_id: str,
        delivery_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        correlation_id = get_correlation_id() or request_id

        if not self._enabled:
            logger.error(
                "provider=email status=error reason=adapter_disabled outcome=disabled "
                "correlation_id=%s request_id=%s",
                correlation_id,
                request_id,
            )
            return {
                "ok": False,
                "status": "error",
                "error": "email_adapter_disabled",
                "fallback_sent": False,
                "operator_review_flagged": True,
                "operator_review_reason": "adapter_disabled",
                "attempts": 0,
                "response_status": None,
            }

        recipient = self._default_recipient
        if isinstance(delivery_context, dict):
            override = str(
                delivery_context.get("email_recipient")
                or delivery_context.get("recipient_id")
                or ""
            ).strip()
            if override:
                recipient = override

        text = _extract_text(data)
        subject = f"{self._subject_prefix} [{request_id}]"
        if isinstance(delivery_context, dict):
            custom_subject = str(delivery_context.get("email_subject") or "").strip()
            if custom_subject:
                subject = custom_subject

        return self._send_with_retry(
            text,
            recipient=recipient,
            subject=subject,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _send_with_retry(
        self,
        text: str,
        *,
        recipient: str,
        subject: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        max_attempts = len(_RETRY_BACKOFF) + 1
        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(_RETRY_BACKOFF[attempt - 1])
            result = self._try_once(
                text,
                recipient=recipient,
                subject=subject,
                attempt=attempt,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            if result is not None:
                return result

        return self._send_fallback(
            recipient=recipient,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _try_once(
        self,
        text: str,
        *,
        recipient: str,
        subject: str,
        attempt: int,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any] | None:
        logger.info(
            "provider=email status=sending attempt=%s request_id=%s correlation_id=%s outcome=attempt",
            attempt,
            request_id,
            correlation_id,
        )
        try:
            self._smtp_send(recipient=recipient, subject=subject, body=text)
            logger.info(
                "provider=email status=sent attempt=%s request_id=%s "
                "correlation_id=%s outcome=success",
                attempt,
                request_id,
                correlation_id,
            )
            return {
                "ok": True,
                "status": "sent",
                "error": None,
                "fallback_sent": False,
                "operator_review_flagged": False,
                "operator_review_reason": None,
                "attempts": attempt + 1,
                "response_status": 250,
            }
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            logger.error(
                "provider=email status=error attempt=%s request_id=%s "
                "correlation_id=%s outcome=request_error error_type=%s",
                attempt,
                request_id,
                correlation_id,
                type(exc).__name__,
            )
            return None

    def _send_fallback(
        self,
        *,
        recipient: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        fallback_text = f"{self._fallback_text} Reference: {request_id}."
        subject = f"{self._subject_prefix} follow-up [{request_id}]"
        fallback_sent = False

        for attempt in range(self._fallback_max_retries):
            try:
                self._smtp_send(recipient=recipient, subject=subject, body=fallback_text)
                fallback_sent = True
                logger.warning(
                    "provider=email status=fallback_sent attempt=%s request_id=%s "
                    "correlation_id=%s outcome=fallback",
                    attempt,
                    request_id,
                    correlation_id,
                )
                break
            except (smtplib.SMTPException, OSError, TimeoutError) as exc:
                logger.error(
                    "provider=email status=fallback_failed attempt=%s request_id=%s "
                    "correlation_id=%s outcome=fallback_error error_type=%s",
                    attempt,
                    request_id,
                    correlation_id,
                    type(exc).__name__,
                )

        return {
            "ok": False,
            "status": "fallback_sent" if fallback_sent else "error",
            "error": None if fallback_sent else "all_attempts_exhausted",
            "fallback_sent": fallback_sent,
            "operator_review_flagged": True,
            "operator_review_reason": (
                "primary_exhausted_fallback_sent"
                if fallback_sent
                else "outbound_fallback_failure"
            ),
            "attempts": len(_RETRY_BACKOFF) + 1,
            "response_status": None,
        }

    def _smtp_send(self, *, recipient: str, subject: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self._from_address
        msg["To"] = recipient

        if self._use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=self._send_timeout) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if self._smtp_username and self._smtp_password:
                    server.login(self._smtp_username, self._smtp_password)
                server.sendmail(self._from_address, [recipient], msg.as_string())
            return

        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=self._send_timeout) as server:
            server.ehlo()
            if self._smtp_username and self._smtp_password:
                server.login(self._smtp_username, self._smtp_password)
            server.sendmail(self._from_address, [recipient], msg.as_string())
