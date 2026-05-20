from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from app.config import get_required_config_keys, normalize_provider
from app.models import AuditLog, ConnectionState, TenantNotification
from app.onboarding import get_connection_state, sync_connection_status
from app.services.channel_interface import (
    CHANNEL_INSTAGRAM,
    CHANNEL_MESSENGER,
    CHANNEL_TELEGRAM,
    CHANNEL_TIKTOK,
    CHANNEL_WHATSAPP,
    get_outbound_channel,
)
from app.services.escalation_queue import append_review_artifact

_CHANNEL_LABELS = {
    CHANNEL_WHATSAPP: "WhatsApp",
    CHANNEL_TELEGRAM: "Telegram",
    CHANNEL_INSTAGRAM: "Instagram",
    CHANNEL_MESSENGER: "Messenger",
    CHANNEL_TIKTOK: "TikTok",
}


@dataclass(frozen=True)
class StepDefinition:
    key: str
    title: str
    diagnosis: str
    instruction: str


FlowResponse = dict[str, Any]
RetryResponse = dict[str, Any]
EscalationResponse = dict[str, Any]
AbandonResponse = dict[str, Any]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _active_channel(app) -> str:
    value = str(app.config.get("OUTBOUND_CHANNEL", CHANNEL_WHATSAPP)).strip().lower()
    return value or CHANNEL_WHATSAPP


def _channel_label(channel: str) -> str:
    return _CHANNEL_LABELS.get(channel, channel.title())


def _probe_telegram_provider(app) -> tuple[bool, str]:
    token = str(app.config.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return False, "telegram_token_missing"

    timeout_val = app.config.get(
        "TELEGRAM_PROBE_TIMEOUT_SECONDS",
        app.config.get("TELEGRAM_SEND_TIMEOUT_SECONDS", 10.0),
    )
    try:
        timeout = float(timeout_val)
        if not (0.1 <= timeout <= 120):
            timeout = 10.0
    except (TypeError, ValueError):
        timeout = 10.0
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=max(0.1, timeout),
        )
        if response.status_code >= 400:
            return False, f"telegram_provider_http_{response.status_code}"
        payload = response.json()
        if not isinstance(payload, dict) or not bool(payload.get("ok")):
            return False, "telegram_provider_payload_invalid"
        return True, "telegram_provider_ok"
    except requests.Timeout:
        return False, "telegram_provider_timeout"
    except (requests.RequestException, ValueError):
        return False, "telegram_provider_unreachable"


def _probe_social_provider(app, channel: str) -> tuple[bool, str]:
    connect_key_map = {
        CHANNEL_INSTAGRAM: "INSTAGRAM_CONNECT_URL",
        CHANNEL_MESSENGER: "MESSENGER_CONNECT_URL",
        CHANNEL_TIKTOK: "TIKTOK_CONNECT_URL",
    }
    outbound_key_map = {
        CHANNEL_INSTAGRAM: "INSTAGRAM_OUTBOUND_URL",
        CHANNEL_MESSENGER: "MESSENGER_OUTBOUND_URL",
        CHANNEL_TIKTOK: "TIKTOK_OUTBOUND_URL",
    }
    timeout_key_map = {
        CHANNEL_INSTAGRAM: ("INSTAGRAM_PROBE_TIMEOUT_SECONDS", "INSTAGRAM_SEND_TIMEOUT_SECONDS"),
        CHANNEL_MESSENGER: ("MESSENGER_PROBE_TIMEOUT_SECONDS", "MESSENGER_SEND_TIMEOUT_SECONDS"),
        CHANNEL_TIKTOK: ("TIKTOK_PROBE_TIMEOUT_SECONDS", "TIKTOK_SEND_TIMEOUT_SECONDS"),
    }

    # Prefer outbound/health endpoint before connect URL fallback
    outbound_url = str(app.config.get(outbound_key_map[channel]) or "").strip()
    connect_url = str(app.config.get(connect_key_map[channel]) or "").strip()
    probe_url = outbound_url or connect_url
    if not probe_url:
        return False, f"{channel}_provider_url_missing"

    probe_timeout_key, fallback_timeout_key = timeout_key_map[channel]
    timeout_val = app.config.get(probe_timeout_key, app.config.get(fallback_timeout_key, 10.0))
    try:
        timeout = float(timeout_val)
        if not (0.1 <= timeout <= 120):
            timeout = 10.0
    except (TypeError, ValueError):
        timeout = 10.0
    try:
        response = requests.get(probe_url, timeout=max(0.1, timeout))
        if response.status_code >= 400:
            return False, f"{channel}_provider_http_{response.status_code}"
        return True, f"{channel}_provider_ok"
    except requests.Timeout:
        return False, f"{channel}_provider_timeout"
    except requests.RequestException:
        return False, f"{channel}_provider_unreachable"


def _resolve_connection_snapshot_with_app(app, db, tenant_id: str, channel: str) -> tuple[str, bool, dict[str, Any]]:
    if channel == CHANNEL_WHATSAPP:
        snapshot = get_connection_state(db, tenant_id)
        status = str(getattr(snapshot, "status", "disconnected") or "disconnected")
        degraded = status != "connected"
        return status, degraded, {"status_source": "connection_states"}

    adapter = get_outbound_channel(app)
    enabled = bool(getattr(adapter, "_enabled", True))  # noqa: SLF001

    if channel == CHANNEL_TELEGRAM:
        ok, detail = _probe_telegram_provider(app)
    elif channel in {CHANNEL_INSTAGRAM, CHANNEL_MESSENGER, CHANNEL_TIKTOK}:
        ok, detail = _probe_social_provider(app, channel)
    else:
        ok, detail = True, "provider_probe_not_required"

    status = "connected" if ok else "degraded"
    return status, not ok, {
        "status_source": "provider_probe",
        "adapter_enabled": enabled,
        "provider_probe": detail,
    }


def _steps_for_channel(channel: str) -> list[StepDefinition]:
    label = _channel_label(channel)
    return [
        StepDefinition(
            key="token",
            title="Refresh token or API key",
            diagnosis=f"{label} may have rejected credentials due to expiry or rotation.",
            instruction="Open channel settings and re-enter the latest token/API key, then save.",
        ),
        StepDefinition(
            key="network",
            title="Validate network reachability",
            diagnosis="The app may be unable to reach the provider endpoint.",
            instruction="Check base URL, DNS, firewall allow-lists, and outbound internet routing.",
        ),
        StepDefinition(
            key="provider",
            title="Check provider status",
            diagnosis="Provider-side outage or degraded API health can block reconnect.",
            instruction="Verify provider status dashboard and retry after incidents are cleared.",
        ),
        StepDefinition(
            key="permissions",
            title="Confirm permissions and configuration",
            diagnosis="Instance permissions or channel config may be incomplete.",
            instruction="Confirm required permissions, instance binding, and tenant channel config.",
        ),
    ]


def _upsert_notification(
    sess,
    *,
    tenant_id: str,
    alert_type: str,
    title: str,
    message: str,
    notification_key: str,
    details: dict[str, Any],
) -> bool:
    existing = (
        sess.query(TenantNotification)
        .filter(
            TenantNotification.tenant_id == tenant_id,
            TenantNotification.notification_key == notification_key,
        )
        .one_or_none()
    )
    if existing is not None:
        return False

    sess.add(
        TenantNotification(
            tenant_id=tenant_id,
            category="connectivity",
            alert_type=alert_type,
            severity="warning",
            title=title,
            message=message,
            notification_key=notification_key,
            details_json=_json_dumps(details),
        )
    )
    return True


def _parse_notification_details(raw_details: str | None) -> dict[str, Any]:
    if not raw_details:
        return {}
    try:
        payload = json.loads(raw_details)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _extract_marker(notification_key: str | None, channel: str) -> str | None:
    key = str(notification_key or "").strip()
    prefix = f"connectivity:reconnection_required:{channel}:"
    if not key.startswith(prefix):
        return None
    marker = key[len(prefix):].strip()
    if len(marker) != 12 or not marker.isdigit():
        return None
    return marker


def _find_active_reconnection_notification(sess, *, tenant_id: str, channel: str):
    rows = (
        sess.query(TenantNotification)
        .filter(
            TenantNotification.tenant_id == tenant_id,
            TenantNotification.alert_type == "reconnection_required",
            TenantNotification.dismissed_at.is_(None),
        )
        .order_by(TenantNotification.created_at.desc())
        .all()
    )
    for row in rows:
        details = _parse_notification_details(row.details_json)
        if str(details.get("channel") or "").strip().lower() == channel:
            return row
    return None


def _find_latest_reconnection_notification(sess, *, tenant_id: str, channel: str):
    rows = (
        sess.query(TenantNotification)
        .filter(
            TenantNotification.tenant_id == tenant_id,
            TenantNotification.alert_type == "reconnection_required",
        )
        .order_by(TenantNotification.created_at.desc())
        .all()
    )
    for row in rows:
        details = _parse_notification_details(row.details_json)
        if str(details.get("channel") or "").strip().lower() == channel:
            return row
    return None


def _append_audit(sess, *, tenant_id: str, actor_id: str | None, actor_type: str, action: str, payload: dict[str, Any]) -> None:
    sess.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            payload=_json_dumps(payload),
        )
    )


def _retry_attempt_count(sess, *, tenant_id: str, window_minutes: int = 60) -> int:
    floor = _utcnow() - timedelta(minutes=window_minutes)
    return int(
        sess.query(AuditLog)
        .filter(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action == "reconnection_assistant.retry",
            AuditLog.created_at >= floor,
        )
        .count()
    )


def sync_reconnection_notifications(app, db, tenant_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Detect degraded connection states and upsert a dashboard CTA notification."""
    current_time = now or _utcnow()
    channel = _active_channel(app)
    status, degraded, diagnostics = _resolve_connection_snapshot_with_app(app, db, tenant_id, channel)

    marker = current_time.strftime("%Y%m%d%H%M")
    detected_within_window: bool | None = None
    detection_window_source = "provider_probe_no_occurrence_timestamp"
    detection_window_val = app.config.get("RECONNECTION_DETECTION_WINDOW_SECONDS", 60)
    try:
        detection_window_seconds = float(detection_window_val)
        if not (1 <= detection_window_seconds <= 3600):
            detection_window_seconds = 60.0
    except (TypeError, ValueError):
        detection_window_seconds = 60.0
    if channel == CHANNEL_WHATSAPP:
        detection_window_source = "connection_states.updated_at"
        sess = db.session()
        try:
            row = (
                sess.query(ConnectionState)
                .filter(ConnectionState.tenant_id == tenant_id)
                .one_or_none()
            )
            if row is not None and row.updated_at is not None:
                updated_at = row.updated_at
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                else:
                    updated_at = updated_at.astimezone(timezone.utc)
                marker = updated_at.strftime("%Y%m%d%H%M")
                detected_within_window = (current_time - updated_at).total_seconds() <= detection_window_seconds
        finally:
            sess.close()

    if not degraded:
        return {
            "detected": False,
            "status": status,
            "channel": channel,
            "notification_created": False,
            "detected_within_window": detected_within_window,
        }

    sess = db.session()
    try:
        if channel != CHANNEL_WHATSAPP:
            detection_window_source = "provider_probe.first_observed_at"
            detected_within_window = True

        active_row = _find_active_reconnection_notification(sess, tenant_id=tenant_id, channel=channel)
        if active_row is not None:
            if channel != CHANNEL_WHATSAPP:
                details = _parse_notification_details(active_row.details_json)
                if isinstance(details.get("detected_within_window"), bool):
                    detected_within_window = details["detected_within_window"]
            return {
                "detected": True,
                "status": status,
                "channel": channel,
                "notification_created": False,
                "detected_within_window": detected_within_window,
            }

        if channel != CHANNEL_WHATSAPP:
            latest = _find_latest_reconnection_notification(sess, tenant_id=tenant_id, channel=channel)
            marker_reuse_val = app.config.get("RECONNECTION_NON_WHATSAPP_MARKER_REUSE_SECONDS", 300)
            try:
                marker_reuse_seconds = int(marker_reuse_val)
                if not (0 <= marker_reuse_seconds <= 86400):
                    marker_reuse_seconds = 300
            except (TypeError, ValueError):
                marker_reuse_seconds = 300
            if latest is not None and latest.created_at is not None:
                created_at = _to_utc(latest.created_at)
                if (current_time - created_at).total_seconds() <= float(max(0, marker_reuse_seconds)):
                    previous_marker = _extract_marker(latest.notification_key, channel)
                    if previous_marker:
                        marker = previous_marker

        key = f"connectivity:reconnection_required:{channel}:{marker}"
        title = f"Reconnect {_channel_label(channel)}"
        message = (
            f"{_channel_label(channel)} is currently {status}. "
            "Open the guided troubleshooting assistant to restore connectivity."
        )
        details = {
            "channel": channel,
            "status": status,
            "call_to_action": "Open guided troubleshooting",
            "flow_api": "/api/reconnection-assistant/flow",
            "retry_api": "/api/reconnection-assistant/steps/{step_key}/retry",
            "escalation_api": "/api/reconnection-assistant/escalate",
            "detected_at": current_time.isoformat(timespec="seconds"),
            "detected_within_window": detected_within_window,
            "detected_within_window_source": detection_window_source,
            "diagnostics": diagnostics,
        }
        created = _upsert_notification(
            sess,
            tenant_id=tenant_id,
            alert_type="reconnection_required",
            title=title,
            message=message,
            notification_key=key,
            details=details,
        )
        if created:
            _append_audit(
                sess,
                tenant_id=tenant_id,
                actor_id=None,
                actor_type="system",
                action="reconnection_assistant.detected",
                payload={
                    "channel": channel,
                    "status": status,
                    "notification_key": key,
                    "detected_within_window": detected_within_window,
                },
            )
        sess.commit()
        return {
            "detected": True,
            "status": status,
            "channel": channel,
            "notification_created": created,
            "detected_within_window": detected_within_window,
        }
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def build_reconnection_flow(
    app,
    db,
    tenant_id: str,
    *,
    actor_id: str | None,
    expected_channel: str | None = None,
) -> FlowResponse:
    channel = _active_channel(app)
    if expected_channel and expected_channel.strip().lower() != channel:
        raise ValueError(
            f"Channel changed from '{expected_channel.strip().lower()}' to '{channel}'. Refresh the guided flow."
        )
    status, degraded, diagnostics = _resolve_connection_snapshot_with_app(app, db, tenant_id, channel)
    steps = _steps_for_channel(channel)

    sess = db.session()
    try:
        _append_audit(
            sess,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type="operator" if actor_id else "system",
            action="reconnection_assistant.flow_opened",
            payload={"channel": channel, "status": status, "degraded": degraded},
        )
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()

    return {
        "ok": True,
        "channel": channel,
        "channel_label": _channel_label(channel),
        "status": status,
        "degraded": degraded,
        "steps": [
            {
                "key": step.key,
                "title": step.title,
                "diagnosis": step.diagnosis,
                "instruction": step.instruction,
                "retry_available": True,
                "retry_endpoint": f"/api/reconnection-assistant/steps/{step.key}/retry",
            }
            for step in steps
        ],
        "escalation": {
            "available": True,
            "endpoint": "/api/reconnection-assistant/escalate",
            "message": "If reconnect still fails, escalate to support with diagnostics.",
        },
        "diagnostics": diagnostics,
    }


def _token_check(app, channel: str) -> tuple[bool, str]:
    if channel == CHANNEL_WHATSAPP:
        provider = normalize_provider(app.config.get("WHATSAPP_PROVIDER"))
        keys = get_required_config_keys(provider)
        token_like = [key for key in keys if "TOKEN" in key or "KEY" in key]
        missing = [key for key in token_like if not app.config.get(key)]
        if missing:
            return False, f"Missing credential values: {', '.join(sorted(missing))}"
        return True, "Credentials are present."

    key_map = {
        CHANNEL_TELEGRAM: ["TELEGRAM_BOT_TOKEN"],
        CHANNEL_INSTAGRAM: ["INSTAGRAM_ACCESS_TOKEN"],
        CHANNEL_MESSENGER: ["MESSENGER_PAGE_ACCESS_TOKEN"],
        CHANNEL_TIKTOK: ["TIKTOK_ACCESS_TOKEN"],
    }
    required = key_map.get(channel, [])
    missing = [key for key in required if not app.config.get(key)]
    if missing:
        return False, f"Missing credential values: {', '.join(sorted(missing))}"
    return True, "Credentials are present."


def _network_check(app, channel: str) -> tuple[bool, str]:
    url_map = {
        CHANNEL_WHATSAPP: "EVOLUTION_API_URL",
        CHANNEL_INSTAGRAM: "INSTAGRAM_OUTBOUND_URL",
        CHANNEL_MESSENGER: "MESSENGER_OUTBOUND_URL",
        CHANNEL_TIKTOK: "TIKTOK_OUTBOUND_URL",
    }
    key = url_map.get(channel)
    if key is None:
        return True, "No network endpoint check required for this channel."

    value = str(app.config.get(key, "")).strip()
    if not value:
        return False, f"{key} is missing."
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, f"{key} must include scheme and host (http:// or https://)."
    return True, f"{key} is configured."


def _provider_check(app, db, tenant_id: str, channel: str) -> tuple[bool, str, str]:
    if channel == CHANNEL_WHATSAPP:
        try:
            snapshot = sync_connection_status(db, app, tenant_id)
            status = str(getattr(snapshot, "status", "disconnected") or "disconnected")
            if status == "connected":
                return True, "Provider reports connected state.", status
            return False, f"Provider still reports '{status}'.", status
        except Exception as exc:  # noqa: BLE001
            return False, f"Provider status check failed: {type(exc).__name__}", "degraded"

    status, degraded, diagnostics = _resolve_connection_snapshot_with_app(app, db, tenant_id, channel)
    if not degraded:
        return True, "Provider probe reports healthy connectivity.", status
    return False, f"Provider probe indicates degraded state: {diagnostics.get('provider_probe')}", status


def _permissions_check(db, tenant_id: str, channel: str) -> tuple[bool, str]:
    if channel != CHANNEL_WHATSAPP:
        return True, "Permissions check passed for selected channel."

    sess = db.session()
    try:
        row = (
            sess.query(ConnectionState)
            .filter(ConnectionState.tenant_id == tenant_id)
            .one_or_none()
        )
        if row is None:
            return False, "No connection state exists for this tenant."
        if not str(row.evolution_instance or "").strip():
            return False, "Tenant is missing an Evolution instance binding."
        return True, "Tenant instance binding is present."
    finally:
        sess.close()


def retry_reconnection_step(
    app,
    db,
    tenant_id: str,
    *,
    step_key: str,
    actor_id: str | None,
    expected_channel: str | None = None,
) -> RetryResponse:
    channel = _active_channel(app)
    if expected_channel and expected_channel.strip().lower() != channel:
        raise ValueError(
            f"Channel changed from '{expected_channel.strip().lower()}' to '{channel}'. Refresh the guided flow."
        )
    allowed_steps = {step.key for step in _steps_for_channel(channel)}
    if step_key not in allowed_steps:
        raise ValueError(f"Unknown troubleshooting step: {step_key}")

    if step_key == "token":
        passed, detail = _token_check(app, channel)
    elif step_key == "network":
        passed, detail = _network_check(app, channel)
    elif step_key == "provider":
        passed, detail, current_status = _provider_check(app, db, tenant_id, channel)
    else:
        passed, detail = _permissions_check(db, tenant_id, channel)

    if step_key != "provider":
        if channel == CHANNEL_WHATSAPP:
            snapshot = get_connection_state(db, tenant_id)
            current_status = str(getattr(snapshot, "status", "disconnected") or "disconnected")
        else:
            _, degraded, _ = _resolve_connection_snapshot_with_app(app, db, tenant_id, channel)
            current_status = "degraded" if degraded else "connected"

    resolved = passed and current_status == "connected"

    sess = db.session()
    try:
        _append_audit(
            sess,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type="operator" if actor_id else "system",
            action="reconnection_assistant.retry",
            payload={
                "channel": channel,
                "step_key": step_key,
                "passed": bool(passed),
                "resolved": bool(resolved),
                "detail": detail,
                "status": current_status,
            },
        )
        attempts = _retry_attempt_count(sess, tenant_id=tenant_id)
        escalate_threshold = int(app.config.get("RECONNECTION_MAX_RETRIES", 3))
        escalate_recommended = (not resolved) and attempts >= escalate_threshold
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()

    return {
        "ok": True,
        "channel": channel,
        "step_key": step_key,
        "step_passed": bool(passed),
        "resolved": bool(resolved),
        "status": current_status,
        "detail": detail,
        "retry_count_last_hour": attempts,
        "escalation_recommended": bool(escalate_recommended),
    }


def escalate_reconnection_issue(
    app,
    db,
    tenant_id: str,
    *,
    actor_id: str | None,
    reason: str | None,
) -> EscalationResponse:
    channel = _active_channel(app)
    issue_reason = (reason or "reconnection_unresolved").strip() or "reconnection_unresolved"
    queued, queue_error = append_review_artifact(
        app,
        correlation_id=None,
        reason=f"reconnection_assistant:{issue_reason}",
        wa_id=None,
        message_id=None,
    )

    success = bool(queued)
    action = "reconnection_assistant.escalated" if success else "reconnection_assistant.escalation_failed"

    sess = db.session()
    try:
        _append_audit(
            sess,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type="operator" if actor_id else "system",
            action=action,
            payload={
                "channel": channel,
                "reason": issue_reason,
                "queue_written": success,
                "queue_error": queue_error,
            },
        )
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()

    return {
        "ok": success,
        "channel": channel,
        "escalated": success,
        "queue_written": success,
        "queue_error": queue_error,
        "reason": issue_reason,
    }


def abandon_reconnection_flow(db, tenant_id: str, *, actor_id: str | None) -> dict[str, Any]:
    sess = db.session()
    try:
        _append_audit(
            sess,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type="operator" if actor_id else "system",
            action="reconnection_assistant.abandoned",
            payload={"event": "flow_abandoned"},
        )
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()

    return {"ok": True, "abandoned": True}
