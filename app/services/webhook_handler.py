"""app/services/webhook_handler.py

Stripe webhook ingestion and entitlement state machine for saas-2-2.

Handles 5 Stripe event types:
  - checkout.session.completed
  - invoice.paid
  - customer.subscription.updated
  - customer.subscription.deleted
  - invoice.payment_failed

Design:
  - Signature verified via stripe.Webhook.construct_event() before any DB work.
  - Events stored append-only in billing_events (idempotent on stripe_event_id).
  - Subscription status updated per state machine after idempotency check.
  - Audit log written per entitlement transition (actor_type='stripe_webhook').
  - Unknown event types acknowledged 200 and stored with no handler side-effects.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.models import AuditLog, BillingEvent, Subscription
from app.models.base import utcnow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stripe subscription status → internal status mapping
# ---------------------------------------------------------------------------

_STRIPE_STATUS_MAP: dict[str, str] = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",        # treated as blocked in v1
    "incomplete": "past_due",    # payment still pending — treat as blocked
    "incomplete_expired": "canceled",
    "canceled": "canceled",
    "paused": "past_due",        # treated as blocked in v1
}

_HANDLED_EVENT_TYPES = frozenset({
    "checkout.session.completed",
    "invoice.paid",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
})


# ---------------------------------------------------------------------------
# Public error type
# ---------------------------------------------------------------------------

class WebhookError(Exception):
    """Raised when a webhook cannot be processed; carries the HTTP status code."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def ingest_webhook_event(
    db,
    payload_bytes: bytes,
    stripe_signature: str,
    stripe_webhook_secret: str,
) -> tuple[int, str]:
    """Verify, deduplicate, store, and dispatch a Stripe webhook event.

    Args:
        db: SaaSDatabase extension instance.
        payload_bytes: Raw request body bytes (required for Stripe signature verification).
        stripe_signature: Value of the ``Stripe-Signature`` HTTP header.
        stripe_webhook_secret: Webhook signing secret from Stripe dashboard.

    Returns:
        ``(status_code, message)`` — (200, "ok") on success,
        (200, "already_processed") on duplicate, raises WebhookError on bad signature.

    Raises:
        WebhookError: When signature verification fails (status_code=400).
    """
    import stripe as _stripe  # noqa: PLC0415 — lazy import for testability

    # 1. Verify signature — must happen before any DB work.
    try:
        event = _stripe.Webhook.construct_event(
            payload_bytes, stripe_signature, stripe_webhook_secret
        )
    except _stripe.SignatureVerificationError as exc:
        logger.warning("WEBHOOK_SIGNATURE_INVALID error=%s", exc)
        raise WebhookError("Webhook signature verification failed.", status_code=400) from exc
    except Exception as exc:
        logger.warning("WEBHOOK_PARSE_ERROR error=%s", exc)
        raise WebhookError("Webhook payload could not be parsed.", status_code=400) from exc

    event_id: str = event["id"]
    event_type: str = event["type"]

    sess = db.session()
    try:
        # 2. Idempotency check — skip if already processed.
        existing = (
            sess.query(BillingEvent)
            .filter(BillingEvent.stripe_event_id == event_id)
            .first()
        )
        if existing is not None:
            logger.info(
                "WEBHOOK_DUPLICATE_SKIPPED event_id=%s type=%s", event_id, event_type
            )
            return 200, "already_processed"

        # 3. Dispatch to handler (before persisting so tenant_id can be attached).
        tenant_id: str | None = None
        if event_type in _HANDLED_EVENT_TYPES:
            tenant_id = _dispatch(sess, event)
        else:
            logger.info(
                "WEBHOOK_UNHANDLED_EVENT type=%s event_id=%s", event_type, event_id
            )

        # 4. Store event in append-only billing_events ledger.
        raw_payload = payload_bytes.decode("utf-8", errors="replace")
        billing_event = BillingEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            tenant_id=tenant_id,
            payload=raw_payload,
        )
        sess.add(billing_event)
        sess.commit()

        logger.info(
            "WEBHOOK_INGESTED event_id=%s type=%s tenant_id=%s",
            event_id,
            event_type,
            tenant_id,
        )
        return 200, "ok"

    except WebhookError:
        sess.rollback()
        raise
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Internal dispatcher
# ---------------------------------------------------------------------------

def _dispatch(sess, event: Any) -> str | None:
    """Route event to the appropriate handler.

    Returns the resolved ``tenant_id`` or ``None`` if it could not be determined.
    """
    event_type: str = event["type"]
    obj: dict = event["data"]["object"]

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(sess, event, obj)
    if event_type == "invoice.paid":
        return _handle_invoice_paid(sess, event, obj)
    if event_type == "customer.subscription.updated":
        return _handle_subscription_updated(sess, event, obj)
    if event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(sess, event, obj)
    if event_type == "invoice.payment_failed":
        return _handle_invoice_payment_failed(sess, event, obj)
    return None


# ---------------------------------------------------------------------------
# Per-event handlers
# ---------------------------------------------------------------------------

def _handle_checkout_completed(sess, event: Any, obj: dict) -> str | None:
    """Handle checkout.session.completed — activate the subscription.

    The session object has:
      - ``subscription``: Stripe subscription ID
      - ``customer``: Stripe customer ID
      - ``metadata.plan_key`` and ``metadata.tenant_id``: set during checkout creation
      - ``status``: Stripe subscription status (if already resolved)
    """
    stripe_sub_id: str = obj.get("subscription") or ""
    customer_id: str = obj.get("customer") or ""
    metadata: dict = obj.get("metadata") or {}
    tenant_id: str = (metadata.get("tenant_id") or "").strip()
    plan_key: str = (metadata.get("plan_key") or "starter").strip().lower()

    sub = _find_sub_by_stripe_id(sess, stripe_sub_id)

    if sub is None and tenant_id:
        # Webhook arrived before /billing/success created the pending subscription.
        # Create it now so the state machine can transition it immediately.
        from app.services.billing_service import CONVERSATION_LIMITS  # noqa: PLC0415

        now = utcnow()
        sub = Subscription(
            tenant_id=tenant_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=stripe_sub_id,
            plan_key=plan_key,
            status="pending_webhook",
            conversation_limit=CONVERSATION_LIMITS.get(plan_key, 0),
            current_period_start=now,
            current_period_end=now,
        )
        sess.add(sub)
        sess.flush()
        logger.info(
            "WEBHOOK_CHECKOUT_SUBSCRIPTION_CREATED tenant_id=%s plan_key=%s",
            tenant_id,
            plan_key,
        )

    if sub is None:
        logger.warning(
            "WEBHOOK_CHECKOUT_NO_SUB stripe_sub_id=%s tenant_id=%s",
            stripe_sub_id,
            tenant_id,
        )
        return tenant_id or None

    # Derive new status: prefer the Stripe-reported status on the checkout session
    # object; fall back to 'active' (the common case for a completed checkout).
    stripe_status: str = obj.get("status") or ""
    new_status = _STRIPE_STATUS_MAP.get(stripe_status, "active")

    _update_sub_status(sess, sub, new_status, event["id"], event["type"])
    return sub.tenant_id


def _handle_invoice_paid(sess, event: Any, obj: dict) -> str | None:
    """Handle invoice.paid — subscription is (re-)activated after successful payment."""
    stripe_sub_id: str = obj.get("subscription") or ""
    sub = _find_sub_by_stripe_id(sess, stripe_sub_id)
    if sub is None:
        logger.warning("WEBHOOK_INVOICE_PAID_NO_SUB stripe_sub_id=%s", stripe_sub_id)
        return None
    _update_sub_status(sess, sub, "active", event["id"], event["type"])
    return sub.tenant_id


def _handle_subscription_updated(sess, event: Any, obj: dict) -> str | None:
    """Handle customer.subscription.updated — map Stripe status to internal status."""
    stripe_sub_id: str = obj.get("id") or ""
    stripe_status: str = obj.get("status") or ""
    sub = _find_sub_by_stripe_id(sess, stripe_sub_id)
    if sub is None:
        logger.warning(
            "WEBHOOK_SUB_UPDATED_NO_SUB stripe_sub_id=%s", stripe_sub_id
        )
        return None
    new_status = _STRIPE_STATUS_MAP.get(stripe_status, stripe_status)
    _update_sub_status(sess, sub, new_status, event["id"], event["type"])
    return sub.tenant_id


def _handle_subscription_deleted(sess, event: Any, obj: dict) -> str | None:
    """Handle customer.subscription.deleted — cancel the subscription."""
    stripe_sub_id: str = obj.get("id") or ""
    sub = _find_sub_by_stripe_id(sess, stripe_sub_id)
    if sub is None:
        logger.warning(
            "WEBHOOK_SUB_DELETED_NO_SUB stripe_sub_id=%s", stripe_sub_id
        )
        return None
    _update_sub_status(sess, sub, "canceled", event["id"], event["type"])
    return sub.tenant_id


def _handle_invoice_payment_failed(sess, event: Any, obj: dict) -> str | None:
    """Handle invoice.payment_failed — mark subscription as past_due (blocked in v1)."""
    stripe_sub_id: str = obj.get("subscription") or ""
    sub = _find_sub_by_stripe_id(sess, stripe_sub_id)
    if sub is None:
        logger.warning(
            "WEBHOOK_PAYMENT_FAILED_NO_SUB stripe_sub_id=%s", stripe_sub_id
        )
        return None
    _update_sub_status(sess, sub, "past_due", event["id"], event["type"])
    return sub.tenant_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_sub_by_stripe_id(sess, stripe_subscription_id: str) -> Subscription | None:
    if not stripe_subscription_id:
        return None
    return (
        sess.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_subscription_id)
        .first()
    )


def _update_sub_status(
    sess,
    sub: Subscription,
    new_status: str,
    event_id: str,
    event_type: str,
) -> None:
    """Update subscription status and write an audit log entry."""
    old_status = sub.status
    sub.status = new_status
    sub.updated_at = utcnow()
    _write_audit(
        sess,
        tenant_id=sub.tenant_id,
        action=f"subscription_{new_status}",
        event_id=event_id,
        payload=json.dumps({
            "event_type": event_type,
            "old_status": old_status,
            "new_status": new_status,
            "stripe_subscription_id": sub.stripe_subscription_id,
        }),
    )
    logger.info(
        "WEBHOOK_STATUS_TRANSITION tenant_id=%s sub_id=%s %s→%s event_id=%s",
        sub.tenant_id,
        sub.stripe_subscription_id,
        old_status,
        new_status,
        event_id,
    )


def _write_audit(
    sess,
    *,
    tenant_id: str,
    action: str,
    event_id: str,
    payload: str | None = None,
) -> None:
    """Append an audit_log row for a webhook-driven entitlement transition."""
    sess.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=event_id,
            actor_type="stripe_webhook",
            action=action,
            payload=payload,
        )
    )
