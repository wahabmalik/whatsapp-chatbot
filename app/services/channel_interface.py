"""
Channel-agnostic outbound delivery interface.

Current adapter: WhatsApp (default, only active adapter).

Extension guide (future SMS / Messenger integration):
  1. Implement a class that inherits from OutboundChannel and overrides send().
  2. Register it in _CHANNEL_REGISTRY under a unique key string.
  3. Set OUTBOUND_CHANNEL=<key> in the environment.
  4. Add the key to SUPPORTED_CHANNELS and the channel's required config keys
     to validate_config (app/config.py) under the same guard.
  No activation paths or credentials are introduced in Story 8.2.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

CHANNEL_WHATSAPP = "whatsapp"

# Only active channel.  Extend when SMS/Messenger stories are scheduled.
SUPPORTED_CHANNELS: tuple[str, ...] = (CHANNEL_WHATSAPP,)


class OutboundChannel(ABC):
    """
    Stable contract for all outbound delivery adapters.

    Every adapter must implement send() and return a delivery result dict
    that matches the shape produced by send_message() in whatsapp_utils.
    """

    @abstractmethod
    def send(
        self,
        data: str,
        *,
        request_id: str,
        delivery_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Deliver *data* to the target channel.

        Args:
            data:             Serialised message payload (JSON string).
            request_id:       Correlation ID propagated from the webhook handler.
            delivery_context: Optional metadata dict for log enrichment and
                              operator review artifact creation.

        Returns:
            dict with at minimum: ok, status, error, fallback_sent,
            operator_review_flagged, operator_review_reason, attempts.
        """


class WhatsAppChannel(OutboundChannel):
    """
    WhatsApp adapter.

    Delegates unconditionally to send_message() in whatsapp_utils so that
    all existing retry, fallback, deferred-delivery, and correlation-ID
    propagation behaviour is fully preserved — zero behaviour change.
    """

    def send(
        self,
        data: str,
        *,
        request_id: str,
        delivery_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Intentional deferred import: whatsapp_utils imports channel_interface at
        # module level (for get_outbound_channel), so importing it here at the
        # module level of channel_interface would create a circular dependency.
        # Deferring to call-time is the standard Python resolution for this pattern.
        # _probe_whatsapp_send_fn() is called from create_app() to verify this path
        # resolves correctly at startup, before the first request is served.
        from app.utils.whatsapp_utils import send_message

        return send_message(data, request_id=request_id, delivery_context=delivery_context)


# ---------------------------------------------------------------------------
# Registry — extend here when future channel adapters are implemented.
# ---------------------------------------------------------------------------
_CHANNEL_REGISTRY: dict[str, type[OutboundChannel]] = {
    CHANNEL_WHATSAPP: WhatsAppChannel,
    # "sms": SMSChannel,        # placeholder — do not activate before SMS story
    # "messenger": MessengerChannel,  # placeholder — do not activate before Messenger story
}


def get_outbound_channel(app) -> OutboundChannel:
    """
    Return the active OutboundChannel instance for *app*.

    Reads OUTBOUND_CHANNEL from app.config (default: "whatsapp").
    An empty or absent value safely resolves to "whatsapp".
    An explicitly unknown value raises ValueError — startup validation
    (validate_config) already blocks webhooks in this case, so reaching
    this function with an unsupported channel name indicates a programming
    error or a test bypass, not a recoverable runtime condition.
    """
    channel_name = (
        str(app.config.get("OUTBOUND_CHANNEL", CHANNEL_WHATSAPP)).strip().lower()
        or CHANNEL_WHATSAPP
    )
    cls = _CHANNEL_REGISTRY.get(channel_name)
    if cls is None:
        raise ValueError(
            f"OUTBOUND_CHANNEL '{channel_name}' is not a supported channel. "
            f"Supported channels: {', '.join(SUPPORTED_CHANNELS)}"
        )
    return cls()


def _probe_whatsapp_send_fn() -> None:
    """
    Verify that the lazy import inside WhatsAppChannel.send() resolves correctly.

    Called once from create_app() so that a broken import path surfaces at
    startup (and is logged) rather than silently failing on the first request.
    Has no side effects beyond triggering the import.
    """
    try:
        from app.utils.whatsapp_utils import send_message as _  # noqa: F401
    except ImportError as exc:
        logging.error(
            "WhatsAppChannel lazy import probe failed — send_message is not importable: %s",
            exc,
        )
        raise
