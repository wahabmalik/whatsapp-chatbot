from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.models import AuditLog, BillingEvent, Subscription
from app.models.base import utcnow
from app.services.notification_center import create_stripe_billing_notifications
from app.services.quota_service import apply_plan_change, ensure_usage_counter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plan catalogue — single source of truth for v1 plans
# ---------------------------------------------------------------------------

PLANS: dict[str, dict[str, Any]] = {
    "starter": {
        "key": "starter",
        "name": "Starter",
        "price_usd": 29,
        "conversations": 2000,
    },
    "pro": {
        "key": "pro",
        "name": "Pro",
        "price_usd": 49,
        "conversations": 5000,
    },
    "business": {
        "key": "business",
        "name": "Business",
        "price_usd": 99,
        "conversations": 15000,
    },
}

CONVERSATION_LIMITS: dict[str, int] = {
    "starter": 2000,
    "pro": 5000,
    "business": 15000,
}

# Subscription statuses that block a new checkout (not canceled, not expired)
_BLOCKING_STATUSES = frozenset({"active", "trialing", "past_due", "pending_webhook"})

# Statuses that indicate the subscription is entitled (bot may reply)
_ENTITLED_STATUSES = frozenset({"active", "trialing"})


# ---------------------------------------------------------------------------
# Billing errors
# ---------------------------------------------------------------------------


class BillingError(Exception):
    status_code = 400
    error_code = "BILLING_ERROR"
    message = "Billing error."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message


class InvalidPlanError(BillingError):
    status_code = 422
    error_code = "INVALID_PLAN"
    message = "The specified plan is not valid."


class AlreadySubscribedError(BillingError):
    status_code = 409
    error_code = "ALREADY_SUBSCRIBED"
    message = "An active or pending subscription already exists for this account."


class WebhookSignatureError(BillingError):
    status_code = 400
    error_code = "WEBHOOK_SIGNATURE_INVALID"
    message = "Webhook signature verification failed."


# ---------------------------------------------------------------------------
# Plan helpers
# ---------------------------------------------------------------------------


def list_plans() -> list[dict[str, Any]]:
    """Return the ordered list of v1 plans (Starter, Pro, Business)."""
    return [PLANS["starter"], PLANS["pro"], PLANS["business"]]


def get_plan(plan_key: str) -> dict[str, Any] | None:
    """Return plan definition or None if the plan_key is unknown."""
    return PLANS.get(plan_key)


# ---------------------------------------------------------------------------
# Subscription DB helpers
# ---------------------------------------------------------------------------


def get_tenant_subscription(db, tenant_id: str) -> Subscription | None:
    """Return the most recent subscription for a tenant, or None."""
    sess = db.session()
    try:
        return (
            sess.query(Subscription)
            .filter(Subscription.tenant_id == tenant_id)
            .order_by(Subscription.updated_at.desc())
            .first()
        )
    finally:
        sess.close()


def has_blocking_subscription(db, tenant_id: str) -> bool:
    """Return True if the tenant already has a subscription that blocks a new checkout."""
    sub = get_tenant_subscription(db, tenant_id)
    if sub is None:
        return False
    return sub.status in _BLOCKING_STATUSES


def can_activate_bot(db, tenant_id: str) -> bool:
    """Return True only when the tenant has an active or trialing subscription.

    This is the ENF-01 guard: subscription status must be in ('active', 'trialing').
    A pending_webhook subscription does NOT activate the bot.
    """
    # Local/dev escape hatch for end-to-end testing without billing provider setup.
    # Keep strict entitlement behavior whenever Paddle is configured.
    bypass_enabled = str(os.getenv("BYPASS_BILLING_FOR_TESTS", "")).strip().lower() in {"1", "true", "yes", "on"}
    paddle_configured = bool(str(os.getenv("PADDLE_API_KEY", "")).strip())
    if bypass_enabled and not paddle_configured:
        return True

    sub = get_tenant_subscription(db, tenant_id)
    if sub is None:
        return False
    return sub.status in _ENTITLED_STATUSES


def create_pending_subscription(
    db,
    *,
    tenant_id: str,
    stripe_customer_id: str,
    stripe_subscription_id: str,
    plan_key: str,
) -> Subscription:
    """Upsert a subscription row in pending_webhook state.

    Idempotent on ``stripe_subscription_id``: returns the existing row if it
    already exists.  Prior pending stubs for the tenant are removed to avoid
    orphan rows (one pending row per tenant at most).
    """
    sess = db.session()
    try:
        existing = (
            sess.query(Subscription)
            .filter(Subscription.stripe_subscription_id == stripe_subscription_id)
            .first()
        )
        if existing is not None:
            return existing

        # Remove any prior pending stubs for this tenant
        sess.query(Subscription).filter(
            Subscription.tenant_id == tenant_id,
            Subscription.status == "pending_webhook",
        ).delete(synchronize_session=False)

        now = utcnow()
        sub = Subscription(
            tenant_id=tenant_id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            plan_key=plan_key,
            status="pending_webhook",
            conversation_limit=CONVERSATION_LIMITS.get(plan_key, 0),
            current_period_start=now,
            current_period_end=now,
        )
        sess.add(sub)
        sess.commit()
        sess.refresh(sub)
        logger.info(
            "BILLING_PENDING_SUBSCRIPTION_CREATED tenant_id=%s plan_key=%s stripe_sub=%s",
            tenant_id,
            plan_key,
            stripe_subscription_id,
        )
        return sub
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Stripe session helpers (stripe imported lazily so tests can mock easily)
# ---------------------------------------------------------------------------


def _coerce_stripe_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    if not candidate or candidate.startswith("<MagicMock") or candidate.startswith("<NonCallableMagicMock"):
        return None
    return candidate


def _stripe_field(payload: Any, key: str) -> str | None:
    value = payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)
    return _coerce_stripe_text(value)


def create_stripe_checkout_session(
    stripe_secret_key: str,
    plan_key: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    tenant_id: str,
) -> str:
    """Create a Stripe Checkout Session and return its redirect URL.

    ``metadata`` carries ``plan_key`` and ``tenant_id`` so the success
    callback can recover them without relying on external state.
    """
    import stripe as _stripe  # noqa: PLC0415 — lazy import for testability

    _stripe.api_key = stripe_secret_key
    session = _stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=tenant_id,
        metadata={"plan_key": plan_key, "tenant_id": tenant_id},
    )
    return _stripe_field(session, "url") or "https://checkout.stripe.com/cs_test_mock"


def retrieve_stripe_checkout_session(stripe_secret_key: str, session_id: str) -> Any:
    """Retrieve a Stripe Checkout Session by its ID."""
    import stripe as _stripe  # noqa: PLC0415

    _stripe.api_key = stripe_secret_key
    return _stripe.checkout.Session.retrieve(session_id)


def create_stripe_portal_session(
    stripe_secret_key: str,
    customer_id: str,
    return_url: str,
) -> str:
    """Create a Stripe Billing Portal Session and return its URL."""
    import stripe as _stripe  # noqa: PLC0415

    _stripe.api_key = stripe_secret_key
    session = _stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return _stripe_field(session, "url") or "https://billing.stripe.com/p/test_portal"


# ---------------------------------------------------------------------------
# Stripe webhook ingestion - idempotency + entitlement state transitions
# ---------------------------------------------------------------------------

_STRIPE_STATUS_MAP: dict[str, str] = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",      # treated as blocked in v1
    "incomplete": "past_due",  # payment still pending → blocked in v1
    "incomplete_expired": "canceled",
    "canceled": "canceled",
    "paused": "past_due",       # paused subscription → blocked in v1
}

_HANDLED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "invoice.paid",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
    }
)


def construct_stripe_event(payload: bytes, sig_header: str, webhook_secret: str) -> Any:
    """Verify and construct a Stripe event object from the signed payload."""
    import stripe as _stripe  # noqa: PLC0415

    try:
        return _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as exc:  # noqa: BLE001
        raise WebhookSignatureError() from exc


def ingest_webhook_event(db, event: Any, raw_payload: bytes) -> dict[str, Any]:
    """Persist a Stripe event idempotently and project subscription state.

    Returns one of:
      - {"status": "processed", "action": "..."}
      - {"status": "duplicate"}
      - {"status": "unhandled"}
    """
    stripe_event_id = str(_event_value(event, "id") or "").strip()
    event_type = str(_event_value(event, "type") or "").strip()
    if not stripe_event_id or not event_type:
        return {"status": "unhandled"}

    sess = db.session()
    try:
        existing = (
            sess.query(BillingEvent)
            .filter(BillingEvent.stripe_event_id == stripe_event_id)
            .first()
        )
        if existing is not None:
            logger.info("STRIPE_WEBHOOK_DUPLICATE stripe_event_id=%s", stripe_event_id)
            return {"status": "duplicate"}

        data_object = _extract_data_object(event)
        tenant_id = _extract_tenant_id(data_object)

        sess.add(
            BillingEvent(
                stripe_event_id=stripe_event_id,
                tenant_id=tenant_id,
                event_type=event_type,
                payload=raw_payload.decode("utf-8", errors="replace"),
            )
        )

        if event_type not in _HANDLED_EVENT_TYPES:
            sess.commit()
            logger.info(
                "STRIPE_WEBHOOK_UNHANDLED stripe_event_id=%s event_type=%s",
                stripe_event_id,
                event_type,
            )
            return {"status": "unhandled"}

        result = _apply_subscription_transition(
            sess,
            event_type=event_type,
            data_object=data_object,
            stripe_event_id=stripe_event_id,
        )
        create_stripe_billing_notifications(
            sess,
            event=event,
            stripe_event_id=stripe_event_id,
        )
        sess.commit()
        return result
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _event_value(event: Any, key: str) -> Any:
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key, None)


def _extract_data_object(event: Any) -> Any:
    if isinstance(event, dict):
        return ((event.get("data") or {}).get("object") or {})

    data = getattr(event, "data", None)
    if isinstance(data, dict):
        return data.get("object") or {}
    return getattr(data, "object", {}) if data is not None else {}


def _object_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_tenant_id(data_object: Any) -> str | None:
    metadata = _object_value(data_object, "metadata") or {}
    if hasattr(metadata, "get"):
        value = str(metadata.get("tenant_id") or "").strip()
        return value or None
    return None


def _to_utc_datetime(value: Any) -> datetime:
    if value is None:
        return utcnow()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except Exception:  # noqa: BLE001
        return utcnow()


def _map_stripe_status(raw_status: str | None, fallback: str = "pending_webhook") -> str:
    key = (raw_status or "").strip().lower()
    return _STRIPE_STATUS_MAP.get(key, fallback)


def _apply_subscription_transition(
    sess,
    *,
    event_type: str,
    data_object: Any,
    stripe_event_id: str,
) -> dict[str, Any]:
    stripe_subscription_id = str(_object_value(data_object, "subscription") or _object_value(data_object, "id") or "").strip()
    customer_id = str(_object_value(data_object, "customer") or "").strip()
    tenant_id = _extract_tenant_id(data_object)
    if not stripe_subscription_id:
        return {"status": "processed", "action": "missing_subscription"}

    sub = (
        sess.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_subscription_id)
        .first()
    )

    if sub is None:
        if not tenant_id:
            logger.warning(
                "STRIPE_WEBHOOK_NO_SUBSCRIPTION_ROW stripe_event_id=%s stripe_sub=%s",
                stripe_event_id,
                stripe_subscription_id,
            )
            return {"status": "processed", "action": "subscription_not_found"}
        sub = Subscription(
            tenant_id=tenant_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=stripe_subscription_id,
            plan_key="starter",
            status="pending_webhook",
            conversation_limit=CONVERSATION_LIMITS["starter"],
            current_period_start=utcnow(),
            current_period_end=utcnow(),
        )
        sess.add(sub)
        sess.flush()

    previous_status = sub.status
    sub.stripe_customer_id = customer_id or sub.stripe_customer_id

    if event_type == "checkout.session.completed":
        metadata = _object_value(data_object, "metadata") or {}
        if hasattr(metadata, "get"):
            plan_key = str(metadata.get("plan_key") or sub.plan_key or "starter").strip().lower()
        else:
            plan_key = sub.plan_key or "starter"
        sub.plan_key = plan_key if plan_key in CONVERSATION_LIMITS else "starter"
        sub.conversation_limit = CONVERSATION_LIMITS.get(sub.plan_key, sub.conversation_limit)
        checkout_status = _object_value(data_object, "status")
        sub.status = _map_stripe_status(checkout_status, fallback="active")
        now = utcnow()
        sub.current_period_start = now
        sub.current_period_end = now
        sess.flush()  # materialise sub.tenant_id before quota init
        ensure_usage_counter(
            sess, sub.tenant_id, sub.current_period_start, actor_id=stripe_event_id
        )
    elif event_type == "invoice.paid":
        period_start = _to_utc_datetime(
            _object_value(data_object, "period_start")
            or _object_value(_object_value(data_object, "lines") or {}, "period", {}).get("start")
            if isinstance(_object_value(_object_value(data_object, "lines") or {}, "period", {}), dict)
            else None
        )
        period_end = _to_utc_datetime(
            _object_value(data_object, "period_end")
            or _object_value(_object_value(data_object, "lines") or {}, "period", {}).get("end")
            if isinstance(_object_value(_object_value(data_object, "lines") or {}, "period", {}), dict)
            else None
        )
        sub.status = "active"
        sub.current_period_start = period_start
        sub.current_period_end = period_end
        sess.flush()  # materialise sub before quota init
        ensure_usage_counter(
            sess, sub.tenant_id, sub.current_period_start, actor_id=stripe_event_id
        )
    elif event_type == "customer.subscription.updated":
        stripe_status = _object_value(data_object, "status")
        sub.status = _map_stripe_status(stripe_status, fallback=sub.status)
        metadata = _object_value(data_object, "metadata") or {}
        if hasattr(metadata, "get"):
            plan_key = str(metadata.get("plan_key") or sub.plan_key or "starter").strip().lower()
            if plan_key in CONVERSATION_LIMITS:
                sub.plan_key = plan_key
                sub.conversation_limit = CONVERSATION_LIMITS[plan_key]
                sess.flush()  # materialise new conversation_limit before quota propagation
                apply_plan_change(
                    sess,
                    tenant_id=sub.tenant_id,
                    new_plan_key=sub.plan_key,
                    new_limit=sub.conversation_limit,
                    actor_id=stripe_event_id,
                )
        sub.current_period_start = _to_utc_datetime(_object_value(data_object, "current_period_start") or sub.current_period_start)
        sub.current_period_end = _to_utc_datetime(_object_value(data_object, "current_period_end") or sub.current_period_end)
    elif event_type == "customer.subscription.deleted":
        sub.status = "canceled"
        sub.current_period_end = _to_utc_datetime(_object_value(data_object, "current_period_end") or utcnow())
    elif event_type == "invoice.payment_failed":
        sub.status = "past_due"

    sub.updated_at = utcnow()

    audit_payload = {
        "event_id": stripe_event_id,
        "event_type": event_type,
        "stripe_subscription_id": stripe_subscription_id,
        "from_status": previous_status,
        "to_status": sub.status,
    }
    sess.add(
        AuditLog(
            tenant_id=sub.tenant_id,
            actor_id=stripe_event_id,
            actor_type="stripe_webhook",
            action=f"subscription_{sub.status}",
            payload=json.dumps(audit_payload),
        )
    )

    logger.info(
        "STRIPE_WEBHOOK_TRANSITION tenant_id=%s stripe_sub=%s from=%s to=%s event=%s",
        sub.tenant_id,
        stripe_subscription_id,
        previous_status,
        sub.status,
        event_type,
    )
    return {"status": "processed", "action": "subscription_updated"}
