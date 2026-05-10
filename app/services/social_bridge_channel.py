"""Bridge-style outbound adapters for social channels.

These adapters make the bot integratable with Instagram, Facebook Messenger,
and TikTok by sending a normalized outbound payload to a configured relay URL.
The relay can be a direct platform endpoint or an internal bridge service.

Current boundary:
    - Instagram and Messenger also have inbound normalization in whatsapp_utils.
    - TikTok remains outbound-only in this repo until a verified inbound webhook
        contract is available.

Contract notes:
  - Same OutboundChannel result shape as WhatsApp and Telegram.
  - Same retry schedule: immediate + retries at 1s / 2s / 4s.
  - Missing required channel config produces a disabled adapter, not a crash.
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

_RETRY_BACKOFF: tuple[int, ...] = (1, 2, 4)
_DEFAULT_FALLBACK_TEXT = (
    "We're experiencing delays right now. A human agent will follow up shortly."
)
_DEFAULT_FALLBACK_MAX_RETRIES = 2


def _extract_text(data: str) -> str:
    """Extract plain-text body from a serialized outbound message payload."""
    try:
        payload = json.loads(data)
        body = payload.get("text", {})
        if isinstance(body, dict):
            return str(body.get("body") or data)
        return str(body) if body else data
    except (json.JSONDecodeError, AttributeError, TypeError):
        return data


class SocialBridgeChannel(OutboundChannel):
    """Shared implementation for HTTP bridge-style social adapters."""

    channel_key = "social"
    recipient_context_key = "recipient_id"

    def __init__(
        self,
        *,
        outbound_url: str | None,
        default_recipient_id: str | None,
        access_token: str | None = None,
        send_timeout: float = 10.0,
        fallback_text: str = _DEFAULT_FALLBACK_TEXT,
        fallback_max_retries: int = _DEFAULT_FALLBACK_MAX_RETRIES,
    ) -> None:
        self._outbound_url = (outbound_url or "").strip()
        self._default_recipient_id = (default_recipient_id or "").strip()
        self._access_token = (access_token or "").strip()
        self._send_timeout = max(0.1, float(send_timeout))
        self._fallback_text = (fallback_text or _DEFAULT_FALLBACK_TEXT).strip()
        self._fallback_max_retries = max(1, int(fallback_max_retries))
        self._enabled = bool(self._outbound_url and self._default_recipient_id)

        if not self._enabled:
            logger.warning(
                "provider=%s status=disabled reason=missing_configuration "
                "outbound_url=%s recipient_id=%s access_token=%s",
                self.channel_key,
                "set" if self._outbound_url else "missing",
                "set" if self._default_recipient_id else "missing",
                "set" if self._access_token else "missing",
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
                "provider=%s status=error reason=adapter_disabled outcome=disabled "
                "correlation_id=%s request_id=%s",
                self.channel_key,
                correlation_id,
                request_id,
            )
            return {
                "ok": False,
                "status": "error",
                "error": f"{self.channel_key}_adapter_disabled",
                "fallback_sent": False,
                "operator_review_flagged": True,
                "operator_review_reason": "adapter_disabled",
                "attempts": 0,
                "response_status": None,
            }

        recipient_id = self._default_recipient_id
        context_payload: dict[str, Any] | None = delivery_context if isinstance(delivery_context, dict) else None
        if context_payload:
            override_recipient_id = str(
                context_payload.get(self.recipient_context_key)
                or context_payload.get("recipient_id")
                or ""
            ).strip()
            if override_recipient_id:
                recipient_id = override_recipient_id

        payload = self._build_payload(
            text=_extract_text(data),
            recipient_id=recipient_id,
            request_id=request_id,
            correlation_id=correlation_id,
            delivery_context=context_payload,
        )
        return self._send_with_retry(
            payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _build_payload(
        self,
        *,
        text: str,
        recipient_id: str,
        request_id: str,
        correlation_id: str,
        delivery_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "channel": self.channel_key,
            "recipient": {"id": recipient_id},
            "message": {"text": text},
            "request_id": request_id,
            "correlation_id": correlation_id,
            "delivery_context": delivery_context or {},
        }

    def _send_with_retry(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        max_attempts = len(_RETRY_BACKOFF) + 1

        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(_RETRY_BACKOFF[attempt - 1])

            result = self._try_once(
                payload,
                attempt=attempt,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            if result is not None:
                return result

        return self._send_fallback(
            recipient_id=str((payload.get("recipient") or {}).get("id") or ""),
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _try_once(
        self,
        payload: dict[str, Any],
        *,
        attempt: int,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any] | None:
        logger.info(
            "provider=%s status=sending attempt=%s request_id=%s correlation_id=%s outcome=attempt",
            self.channel_key,
            attempt,
            request_id,
            correlation_id,
        )

        try:
            response = requests.post(
                self._outbound_url,
                json=payload,
                headers=self._headers(),
                timeout=self._send_timeout,
            )
            response.raise_for_status()
            logger.info(
                "provider=%s status=sent attempt=%s request_id=%s "
                "correlation_id=%s outcome=success response_status=%s",
                self.channel_key,
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
                "provider=%s status=timeout attempt=%s request_id=%s "
                "correlation_id=%s outcome=timeout",
                self.channel_key,
                attempt,
                request_id,
                correlation_id,
            )
            return None
        except requests.RequestException as exc:
            logger.error(
                "provider=%s status=error attempt=%s request_id=%s "
                "correlation_id=%s outcome=request_error error_type=%s",
                self.channel_key,
                attempt,
                request_id,
                correlation_id,
                type(exc).__name__,
            )
            return None

    def _send_fallback(
        self,
        *,
        recipient_id: str,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        payload = self._build_payload(
            text=f"{self._fallback_text} Reference: {request_id}.",
            recipient_id=recipient_id,
            request_id=request_id,
            correlation_id=correlation_id,
            delivery_context=None,
        )
        fallback_sent = False

        for attempt in range(self._fallback_max_retries):
            try:
                response = requests.post(
                    self._outbound_url,
                    json=payload,
                    headers=self._headers(),
                    timeout=self._send_timeout,
                )
                response.raise_for_status()
                fallback_sent = True
                logger.warning(
                    "provider=%s status=fallback_sent attempt=%s request_id=%s "
                    "correlation_id=%s outcome=fallback",
                    self.channel_key,
                    attempt,
                    request_id,
                    correlation_id,
                )
                break
            except requests.RequestException as exc:
                logger.error(
                    "provider=%s status=fallback_failed attempt=%s request_id=%s "
                    "correlation_id=%s outcome=fallback_error error_type=%s",
                    self.channel_key,
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


class InstagramChannel(SocialBridgeChannel):
    channel_key = "instagram"
    recipient_context_key = "instagram_recipient_id"

    @classmethod
    def from_app(cls, app) -> "InstagramChannel":
        return cls(
            outbound_url=app.config.get("INSTAGRAM_OUTBOUND_URL"),
            default_recipient_id=app.config.get("INSTAGRAM_DEFAULT_RECIPIENT_ID"),
            access_token=app.config.get("INSTAGRAM_ACCESS_TOKEN"),
            send_timeout=float(app.config.get("INSTAGRAM_SEND_TIMEOUT_SECONDS", 10.0)),
            fallback_text=app.config.get("OUTBOUND_FALLBACK_TEXT", _DEFAULT_FALLBACK_TEXT),
            fallback_max_retries=int(app.config.get("WHATSAPP_FALLBACK_MAX_RETRIES", 2)),
        )


class MessengerChannel(SocialBridgeChannel):
    channel_key = "messenger"
    recipient_context_key = "messenger_recipient_id"

    @classmethod
    def from_app(cls, app) -> "MessengerChannel":
        return cls(
            outbound_url=app.config.get("MESSENGER_OUTBOUND_URL"),
            default_recipient_id=app.config.get("MESSENGER_DEFAULT_RECIPIENT_ID"),
            access_token=app.config.get("MESSENGER_PAGE_ACCESS_TOKEN"),
            send_timeout=float(app.config.get("MESSENGER_SEND_TIMEOUT_SECONDS", 10.0)),
            fallback_text=app.config.get("OUTBOUND_FALLBACK_TEXT", _DEFAULT_FALLBACK_TEXT),
            fallback_max_retries=int(app.config.get("WHATSAPP_FALLBACK_MAX_RETRIES", 2)),
        )


class TikTokChannel(SocialBridgeChannel):
    channel_key = "tiktok"
    recipient_context_key = "tiktok_recipient_id"

    @classmethod
    def from_app(cls, app) -> "TikTokChannel":
        return cls(
            outbound_url=app.config.get("TIKTOK_OUTBOUND_URL"),
            default_recipient_id=app.config.get("TIKTOK_DEFAULT_RECIPIENT_ID"),
            access_token=app.config.get("TIKTOK_ACCESS_TOKEN"),
            send_timeout=float(app.config.get("TIKTOK_SEND_TIMEOUT_SECONDS", 10.0)),
            fallback_text=app.config.get("OUTBOUND_FALLBACK_TEXT", _DEFAULT_FALLBACK_TEXT),
            fallback_max_retries=int(app.config.get("WHATSAPP_FALLBACK_MAX_RETRIES", 2)),
        )