"""Telegram outbound delivery adapter — Story 9.2.

Wired behind the OutboundChannel interface. Activates when OUTBOUND_CHANNEL=telegram.

Credentials:
    TELEGRAM_BOT_TOKEN       — Bot API token from @BotFather (required).
    TELEGRAM_DEFAULT_CHAT_ID — Target chat/group ID for message routing (required).

Disabled state:
    If either credential is absent at construction time, the adapter sets
    _enabled=False, logs a warning, and returns an error result dict on every
    send() call — no exception is raised, no crash occurs.

Retry contract:
    Same schedule as WhatsApp path: 4 total attempts (immediate + 3 retried at
    1s/2s/4s), then a 2-attempt fallback text send on exhaustion.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from app.services.channel_interface import OutboundChannel
from app.services.observability import get_correlation_id

logger = logging.getLogger(__name__)

CHANNEL_KEY = "telegram"

_API_BASE = "https://api.telegram.org"

# Must match _retry_backoff_schedule() in whatsapp_utils.py — (1, 2, 4) seconds.
_RETRY_BACKOFF: tuple[int, ...] = (1, 2, 4)

_DEFAULT_FALLBACK_TEXT = (
    "We're experiencing delays right now. A human agent will follow up shortly."
)
_DEFAULT_FALLBACK_MAX_RETRIES = 2


def _extract_text(data: str) -> str:
    """Extract plain-text body from a serialised outbound message payload.

    Expects a WhatsApp-format JSON string: ``{"text": {"body": "..."}, ...}``.
    Falls back to the raw *data* string if JSON parsing fails or the expected
    key is absent so that the adapter always has something to send.
    """
    try:
        payload = json.loads(data)
        body = payload.get("text", {})
        if isinstance(body, dict):
            return str(body.get("body") or data)
        return str(body) if body else data
    except (json.JSONDecodeError, AttributeError, TypeError):
        return data


class TelegramChannel(OutboundChannel):
    """Telegram Bot API outbound adapter.

    Implements OutboundChannel.send() with the same retry/fallback semantics
    as the WhatsApp path.
    """

    def __init__(
        self,
        bot_token: str | None,
        default_chat_id: str | None,
        send_timeout: float = 10.0,
        fallback_text: str = _DEFAULT_FALLBACK_TEXT,
        fallback_max_retries: int = _DEFAULT_FALLBACK_MAX_RETRIES,
    ) -> None:
        # Never store raw credentials in repr-able attributes that could leak.
        self._bot_token = (bot_token or "").strip()
        self._default_chat_id = (default_chat_id or "").strip()
        self._send_timeout = max(0.1, float(send_timeout))
        self._fallback_text = (fallback_text or _DEFAULT_FALLBACK_TEXT).strip()
        self._fallback_max_retries = max(1, int(fallback_max_retries))
        self._enabled = bool(self._bot_token and self._default_chat_id)

        if not self._enabled:
            # AC 9.2.2: missing credentials → disabled state with warning log,
            # no crash.  Log "set"/"missing" only — never the token value.
            logger.warning(
                "provider=telegram status=disabled reason=missing_credentials "
                "bot_token=%s default_chat_id=%s",
                "set" if self._bot_token else "missing",
                "set" if self._default_chat_id else "missing",
            )

    @classmethod
    def from_app(cls, app) -> "TelegramChannel":
        """Construct adapter from Flask app config."""
        return cls(
            bot_token=app.config.get("TELEGRAM_BOT_TOKEN"),
            default_chat_id=app.config.get("TELEGRAM_DEFAULT_CHAT_ID"),
            send_timeout=float(app.config.get("TELEGRAM_SEND_TIMEOUT_SECONDS", 10.0)),
            fallback_text=app.config.get("OUTBOUND_FALLBACK_TEXT", _DEFAULT_FALLBACK_TEXT),
            fallback_max_retries=int(app.config.get("WHATSAPP_FALLBACK_MAX_RETRIES", 2)),
        )

    # ------------------------------------------------------------------
    # OutboundChannel contract
    # ------------------------------------------------------------------

    def send(
        self,
        data: str,
        *,
        request_id: str,
        delivery_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deliver message via Telegram Bot API.

        Returns a result dict matching the OutboundChannel contract shape:
        ok, status, error, fallback_sent, operator_review_flagged,
        operator_review_reason, attempts, response_status.

        AC 9.2.4: provider and correlation_id always present in logs.
        No credential values are logged.
        """
        correlation_id = get_correlation_id() or request_id

        if not self._enabled:
            # AC 9.2.2: disabled state returns an error result, no exception.
            logger.error(
                "provider=telegram status=error reason=adapter_disabled outcome=disabled "
                "correlation_id=%s request_id=%s",
                correlation_id,
                request_id,
            )
            return {
                "ok": False,
                "status": "error",
                "error": "telegram_adapter_disabled",
                "fallback_sent": False,
                "operator_review_flagged": True,
                "operator_review_reason": "adapter_disabled",
                "attempts": 0,
                "response_status": None,
            }

        chat_id = self._default_chat_id
        if isinstance(delivery_context, dict):
            override_chat_id = str(delivery_context.get("telegram_chat_id") or "").strip()
            if override_chat_id:
                chat_id = override_chat_id

        text = _extract_text(data)
        return self._send_with_retry(
            text,
            chat_id=chat_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_with_retry(
        self,
        text: str,
        *,
        chat_id: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Retry loop matching the WhatsApp backoff schedule.

        AC 9.2.5: same 4-attempt schedule (immediate + 3 at 1s/2s/4s) then
        fallback text on exhaustion.
        """
        max_attempts = len(_RETRY_BACKOFF) + 1  # 4 total

        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(_RETRY_BACKOFF[attempt - 1])

            result = self._try_once(
                text,
                chat_id=chat_id,
                attempt=attempt,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            if result is not None:
                return result

        return self._send_fallback(
            chat_id=chat_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _try_once(
        self,
        text: str,
        *,
        chat_id: str,
        attempt: int,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any] | None:
        """Single send attempt.

        Returns a result dict on success, None on a recoverable failure so that
        the retry loop can continue.
        """
        url = f"{_API_BASE}/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}

        # AC 9.2.4: provider and correlation_id in every log line; no token value.
        logger.info(
            "provider=telegram status=sending attempt=%s request_id=%s correlation_id=%s outcome=attempt",
            attempt,
            request_id,
            correlation_id,
        )

        try:
            response = requests.post(url, json=payload, timeout=self._send_timeout)
            response.raise_for_status()
            logger.info(
                "provider=telegram status=sent attempt=%s request_id=%s "
                "correlation_id=%s outcome=success response_status=%s",
                attempt,
                request_id,
                correlation_id,
                response.status_code,
            )
            return {
                "ok": True,
                "status": "sent",
                "error": None,
                "fallback_sent": False,
                "operator_review_flagged": False,
                "operator_review_reason": None,
                "attempts": attempt + 1,
                "response_status": response.status_code,
            }
        except requests.Timeout:
            logger.warning(
                "provider=telegram status=timeout attempt=%s request_id=%s "
                "correlation_id=%s outcome=timeout",
                attempt,
                request_id,
                correlation_id,
            )
            return None
        except requests.RequestException as e:
            logger.error(
                "provider=telegram status=error attempt=%s request_id=%s "
                "correlation_id=%s outcome=request_error error_type=%s",
                attempt,
                request_id,
                correlation_id,
                type(e).__name__,
            )
            return None

    def _send_fallback(
        self,
        *,
        chat_id: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Send generic fallback text after all primary retries are exhausted.

        AC 9.2.5: same fallback semantics as WhatsApp path.
        """
        fallback_text = f"{self._fallback_text} Reference: {request_id}."
        url = f"{_API_BASE}/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": fallback_text}
        fallback_sent = False

        for attempt in range(self._fallback_max_retries):
            try:
                response = requests.post(url, json=payload, timeout=self._send_timeout)
                response.raise_for_status()
                fallback_sent = True
                logger.warning(
                    "provider=telegram status=fallback_sent attempt=%s request_id=%s "
                    "correlation_id=%s outcome=fallback",
                    attempt,
                    request_id,
                    correlation_id,
                )
                break
            except requests.RequestException as exc:
                logger.error(
                    "provider=telegram status=fallback_failed attempt=%s request_id=%s "
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
