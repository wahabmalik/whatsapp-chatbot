from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from app.models import Subscription, TenantNotification
from app.services.conversation_analytics import get_retained_analytics_events


def _coerce_thresholds(raw_value: Any) -> list[int]:
    values: list[int] = []
    for token in str(raw_value or "80").split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            value = int(candidate)
        except ValueError:
            continue
        if 1 <= value <= 100:
            values.append(value)
    if not values:
        return [80]
    return sorted(set(values))


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _event_value(event: Any, key: str) -> Any:
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key, None)


def _object_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_data_object(event: Any) -> Any:
    if isinstance(event, dict):
        return ((event.get("data") or {}).get("object") or {})

    data = getattr(event, "data", None)
    if isinstance(data, dict):
        return data.get("object") or {}
    return getattr(data, "object", {}) if data is not None else {}


def _extract_tenant_id(data_object: Any) -> str | None:
    metadata = _object_value(data_object, "metadata") or {}
    if hasattr(metadata, "get"):
        tenant_id = str(metadata.get("tenant_id") or "").strip()
        return tenant_id or None
    return None


def _to_utc_datetime(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    
    # Try parsing as ISO format string first
    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                pass
    
    # Try parsing as Unix timestamp
    try:
        return datetime.fromtimestamp(int(float(value)), tz=timezone.utc)
    except (ValueError, TypeError):  # noqa: BLE001
        return datetime.now(timezone.utc)


def _upsert_tenant_notification(
    sess,
    *,
    tenant_id: str,
    category: str,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    notification_key: str,
    details: dict[str, Any] | None = None,
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
            category=category,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            notification_key=notification_key,
            details_json=_json_dumps(details or {}),
        )
    )
    return True


def create_stripe_billing_notifications(sess, *, event: Any, stripe_event_id: str) -> int:
    """Create tenant-scoped notification records from Stripe webhook events.

    This is event-driven and called directly from webhook ingestion (no polling).
    """
    created = 0
    event_type = str(_event_value(event, "type") or "").strip()
    if not event_type:
        return 0

    data_object = _extract_data_object(event)
    tenant_id = _extract_tenant_id(data_object)
    if not tenant_id:
        return 0

    subscription_id = str(
        _object_value(data_object, "subscription")
        or _object_value(data_object, "id")
        or ""
    ).strip() or "unknown-subscription"

    if event_type == "invoice.payment_failed":
        created += int(
            _upsert_tenant_notification(
                sess,
                tenant_id=tenant_id,
                category="billing",
                alert_type="payment_failed",
                severity="error",
                title="Payment failure detected",
                message="A recent invoice payment failed. Update your billing method to avoid service interruption.",
                notification_key=f"billing:payment_failed:{stripe_event_id}",
                details={"stripe_event_id": stripe_event_id, "subscription_id": subscription_id},
            )
        )

    status = str(_object_value(data_object, "status") or "").strip().lower()
    if status == "trialing":
        period_end = _to_utc_datetime(_object_value(data_object, "current_period_end"))
        now = datetime.now(timezone.utc)
        seconds_remaining = (period_end - now).total_seconds()
        days_remaining = max(0, int(math.ceil(seconds_remaining / 86400.0)))
        period_marker = period_end.date().isoformat()

        if days_remaining <= 7:
            created += int(
                _upsert_tenant_notification(
                    sess,
                    tenant_id=tenant_id,
                    category="billing",
                    alert_type="trial_expiry_7d",
                    severity="warning",
                    title="Trial ends soon",
                    message=f"Your trial period ends in {days_remaining} day(s).",
                    notification_key=f"billing:trial_expiry_7d:{subscription_id}:{period_marker}",
                    details={
                        "stripe_event_id": stripe_event_id,
                        "subscription_id": subscription_id,
                        "days_remaining": days_remaining,
                    },
                )
            )

        if days_remaining <= 1:
            created += int(
                _upsert_tenant_notification(
                    sess,
                    tenant_id=tenant_id,
                    category="billing",
                    alert_type="trial_expiry_1d",
                    severity="error",
                    title="Trial expires in 24 hours",
                    message="Your trial expires in less than 24 hours. Add a payment method to keep service active.",
                    notification_key=f"billing:trial_expiry_1d:{subscription_id}:{period_marker}",
                    details={
                        "stripe_event_id": stripe_event_id,
                        "subscription_id": subscription_id,
                        "days_remaining": days_remaining,
                    },
                )
            )

    return created


def sync_usage_threshold_notifications(app, db, tenant_id: str) -> int:
    """Create usage-threshold notifications based on Story 10.1 analytics events."""
    sess = db.session()
    try:
        subscription = (
            sess.query(Subscription)
            .filter(Subscription.tenant_id == tenant_id)
            .order_by(Subscription.updated_at.desc())
            .first()
        )
        if subscription is None or int(subscription.conversation_limit or 0) <= 0:
            return 0

        thresholds = _coerce_thresholds(app.config.get("USAGE_ALERT_THRESHOLD_PCTS", "80"))
        period_start = _to_utc_datetime(subscription.current_period_start)
        period_marker = period_start.date().isoformat()

        events = get_retained_analytics_events(app, retention_days=int(app.config.get("ANALYTICS_RETENTION_DAYS", 90)))
        unique_conversations: set[str] = set()
        for event in events:
            if not isinstance(event, dict):
                continue
            if str(event.get("stage") or "") != "inbound_receive":
                continue
            if str(event.get("tenant_id") or "") != tenant_id:
                continue
            timestamp = _to_utc_datetime(event.get("timestamp"))
            if timestamp < period_start:
                continue
            conversation_key = str(event.get("conversation_key") or "").strip()
            if not conversation_key:
                continue
            unique_conversations.add(conversation_key)

        used = len(unique_conversations)
        limit = int(subscription.conversation_limit or 0)
        usage_percent = (used / limit) * 100.0 if limit else 0.0

        created = 0
        for threshold in thresholds:
            if usage_percent < threshold:
                continue
            created += int(
                _upsert_tenant_notification(
                    sess,
                    tenant_id=tenant_id,
                    category="usage",
                    alert_type=f"usage_threshold_{threshold}",
                    severity="warning" if threshold < 100 else "error",
                    title=f"Usage reached {threshold}%",
                    message=(
                        f"You have used {used} of {limit} monthly conversations "
                        f"({usage_percent:.1f}%)."
                    ),
                    notification_key=f"usage:threshold:{threshold}:{period_marker}",
                    details={
                        "threshold_pct": threshold,
                        "conversations_used": used,
                        "conversation_limit": limit,
                        "usage_percent": round(usage_percent, 2),
                    },
                )
            )

        if created:
            sess.commit()
        return created
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def list_tenant_notifications(db, tenant_id: str) -> list[dict[str, Any]]:
    sess = db.session()
    try:
        rows = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.tenant_id == tenant_id,
                TenantNotification.dismissed_at.is_(None),
            )
            .order_by(TenantNotification.created_at.desc())
            .all()
        )
        payload: list[dict[str, Any]] = []
        for row in rows:
            details: dict[str, Any] = {}
            if row.details_json:
                try:
                    parsed = json.loads(row.details_json)
                    if isinstance(parsed, dict):
                        details = parsed
                except json.JSONDecodeError:
                    details = {}
            payload.append(
                {
                    "id": row.id,
                    "category": row.category,
                    "alert_type": row.alert_type,
                    "severity": row.severity,
                    "title": row.title,
                    "message": row.message,
                    "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
                    "details": details,
                }
            )
        return payload
    finally:
        sess.close()


def dismiss_tenant_notification(db, *, tenant_id: str, notification_id: str) -> bool:
    sess = db.session()
    try:
        row = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.id == notification_id,
                TenantNotification.tenant_id == tenant_id,
                TenantNotification.dismissed_at.is_(None),
            )
            .one_or_none()
        )
        if row is None:
            return False

        row.dismissed_at = datetime.now(timezone.utc)
        sess.commit()
        return True
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
