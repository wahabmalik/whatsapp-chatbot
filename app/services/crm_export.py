from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests


logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 5.0


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_timeout(app) -> float:
    try:
        return max(0.1, float(app.config.get("CRM_EXPORT_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS


def crm_export_enabled(app) -> bool:
    return bool(app.config.get("CRM_EXPORT_ENABLED", False))


def export_analytics_event_to_crm(app, event: dict[str, Any]) -> bool:
    """Best-effort export of analytics events to an external CRM webhook.

    This is intentionally non-blocking for the request lifecycle. Any failure logs
    and returns False without raising.
    """
    if not crm_export_enabled(app):
        return False

    webhook_url = str(app.config.get("CRM_EXPORT_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        logger.warning("CRM_EXPORT_SKIPPED reason=missing_webhook_url")
        return False

    api_key = str(app.config.get("CRM_EXPORT_API_KEY") or "").strip()
    headers = {
        "Content-Type": "application/json",
        "X-Malixis-Event-Source": "conversation_analytics",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "event_type": "crm_lite.event",
        "exported_at": _utc_timestamp(),
        "event": dict(event),
    }

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=_resolve_timeout(app),
        )
        response.raise_for_status()
        logger.info(
            "CRM_EXPORT_OK stage=%s correlation_id=%s response_status=%s",
            event.get("stage"),
            event.get("correlation_id"),
            response.status_code,
        )
        return True
    except requests.RequestException as exc:
        logger.warning(
            "CRM_EXPORT_FAILED stage=%s correlation_id=%s error_type=%s",
            event.get("stage"),
            event.get("correlation_id"),
            type(exc).__name__,
        )
        return False
