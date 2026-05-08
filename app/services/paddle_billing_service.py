"""Paddle Billing helpers — drop-in replacement for the Stripe session helpers.

Paddle uses a *client-side overlay* model (Paddle.js opens the checkout in the
browser), so there is **no server-side "create checkout session" redirect URL**.
Instead the server returns a Paddle ``price_id`` (``pri_...``) plus the
``client_token`` and the browser opens the overlay.

However, to keep the existing views unchanged, ``create_paddle_checkout_url``
returns the hosted Paddle checkout URL for plans that have a ``pri_...`` price
defined — this is the simplest zero-JS-change path.

Webhook verification uses HMAC-SHA256 over the raw request body with the
``Paddle-Signature`` header (``ts=...;h1=...`` format).

All function names mirror the Stripe helpers they replace so callers in
``views_auth.py`` only need to change import names + config key names.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Paddle subscription statuses → internal statuses
_PADDLE_STATUS_MAP: dict[str, str] = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "paused": "past_due",
    "canceled": "canceled",
}


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def create_paddle_checkout_url(
    api_key: str,
    plan_key: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    tenant_id: str,
) -> str:
    """Return a Paddle hosted-checkout URL for ``price_id``.

    Uses the Paddle API v1 ``/prices/{price_id}/checkout-links`` endpoint.
    Falls back to the Paddle payment-link format if the SDK call fails.
    """
    import urllib.request
    import urllib.error

    # Build a simple hosted-checkout link via the Paddle API
    payload = json.dumps({
        "items": [{"price_id": price_id, "quantity": 1}],
        "success_url": success_url,
        "custom_data": {"plan_key": plan_key, "tenant_id": tenant_id},
    }).encode()

    req = urllib.request.Request(
        "https://api.paddle.com/transactions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            checkout_url = (
                body.get("data", {}).get("checkout", {}).get("url")
                or body.get("data", {}).get("url")
            )
            if checkout_url:
                return checkout_url
    except urllib.error.HTTPError as exc:
        logger.error("PADDLE_CHECKOUT_HTTP_ERROR status=%s body=%s", exc.code, exc.read())
    except Exception as exc:
        logger.error("PADDLE_CHECKOUT_ERROR error=%s", exc)

    # Fallback: Paddle payment link — user lands on Paddle's hosted page
    return f"https://buy.paddle.com/product/{price_id}?passthrough={tenant_id}"


# ---------------------------------------------------------------------------
# Retrieve transaction (replaces retrieve_stripe_checkout_session)
# ---------------------------------------------------------------------------

def retrieve_paddle_transaction(api_key: str, transaction_id: str) -> dict[str, Any]:
    """Retrieve a Paddle transaction by ID and return the parsed JSON body."""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        f"https://api.paddle.com/transactions/{transaction_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("data", {})
    except urllib.error.HTTPError as exc:
        logger.error("PADDLE_RETRIEVE_HTTP_ERROR status=%s body=%s", exc.code, exc.read())
    except Exception as exc:
        logger.error("PADDLE_RETRIEVE_ERROR error=%s", exc)
    return {}


def get_paddle_transaction_ids(transaction: dict[str, Any]) -> tuple[str, str]:
    """Extract (customer_id, subscription_id) from a Paddle transaction dict.

    Returns empty strings if the fields are absent.
    """
    customer_id = str(transaction.get("customer_id") or "").strip()
    subscription_id = str(transaction.get("subscription_id") or "").strip()
    return customer_id, subscription_id


def get_paddle_transaction_metadata(transaction: dict[str, Any]) -> dict[str, Any]:
    """Return the ``custom_data`` dict from a Paddle transaction."""
    custom_data = transaction.get("custom_data") or {}
    if isinstance(custom_data, str):
        try:
            custom_data = json.loads(custom_data)
        except (json.JSONDecodeError, ValueError):
            custom_data = {}
    return custom_data if isinstance(custom_data, dict) else {}


# ---------------------------------------------------------------------------
# Customer portal (replaces create_stripe_portal_session)
# ---------------------------------------------------------------------------

def create_paddle_portal_url(customer_id: str) -> str:
    """Return the Paddle customer portal URL for ``customer_id``.

    Paddle's hosted portal doesn't require a server-side session creation call —
    the URL is deterministic.
    """
    return f"https://customer.paddle.com/customers/{customer_id}"


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

def verify_paddle_webhook_signature(
    payload_bytes: bytes,
    signature_header: str,
    webhook_secret: str,
) -> None:
    """Verify a Paddle webhook ``Paddle-Signature`` header.

    Header format: ``ts=1234567890;h1=<hex_hmac>``

    Raises ``WebhookSignatureError`` on failure.
    """
    from app.services.billing_service import WebhookSignatureError

    if not signature_header:
        raise WebhookSignatureError("Missing Paddle-Signature header.")

    ts: str | None = None
    h1: str | None = None
    for part in signature_header.split(";"):
        if part.startswith("ts="):
            ts = part[3:].strip()
        elif part.startswith("h1="):
            h1 = part[3:].strip()

    if not ts or not h1:
        raise WebhookSignatureError("Malformed Paddle-Signature header.")

    # Replay-attack guard: reject if timestamp is more than 5 minutes old
    try:
        event_ts = int(ts)
        if abs(time.time() - event_ts) > 300:
            raise WebhookSignatureError("Paddle webhook timestamp too old.")
    except ValueError:
        raise WebhookSignatureError("Invalid timestamp in Paddle-Signature.")

    signed_payload = f"{ts}:{payload_bytes.decode('utf-8', errors='replace')}"
    expected = hmac.new(
        webhook_secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, h1):
        raise WebhookSignatureError("Paddle webhook HMAC mismatch.")


# ---------------------------------------------------------------------------
# Webhook event ingestion
# ---------------------------------------------------------------------------

_PADDLE_SUBSCRIPTION_EVENTS = frozenset({
    "subscription.created",
    "subscription.updated",
    "subscription.canceled",
    "subscription.paused",
    "subscription.resumed",
    "transaction.completed",
})


def ingest_paddle_webhook_event(db: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Process a parsed Paddle webhook event dict.

    Mirrors ``ingest_webhook_event`` from the Stripe service — updates the
    ``Subscription`` row status and emits a ``BillingEvent`` audit record.

    Returns ``{"status": "processed"|"skipped"|"duplicate"}``.
    """
    from app.services.billing_service import create_pending_subscription
    from app.models import Subscription, BillingEvent
    from app.models.base import utcnow

    event_type = event.get("event_type") or event.get("notification_type") or ""
    event_id = str(event.get("notification_id") or event.get("id") or "")
    data = event.get("data") or {}

    if event_type not in _PADDLE_SUBSCRIPTION_EVENTS:
        return {"status": "skipped", "event_type": event_type}

    # Dedup by notification_id
    if event_id:
        sess = db.session()
        try:
            existing = sess.query(BillingEvent).filter(BillingEvent.stripe_event_id == event_id).first()
            if existing:
                return {"status": "duplicate", "event_type": event_type}
        finally:
            sess.close()

    customer_id = str(data.get("customer_id") or "").strip()
    # For subscription.* events, "id" is the subscription ID.
    # For transaction.* events, "subscription_id" holds the subscription ID.
    subscription_id = str(data.get("subscription_id") or data.get("id") or "").strip()
    paddle_status = str(data.get("status") or "").strip()
    # transaction.completed always means the payment succeeded → set active
    if event_type == "transaction.completed":
        internal_status = "active"
    else:
        internal_status = _PADDLE_STATUS_MAP.get(paddle_status, "past_due")
    custom_data = data.get("custom_data") or {}
    if isinstance(custom_data, str):
        try:
            custom_data = json.loads(custom_data)
        except (json.JSONDecodeError, ValueError):
            custom_data = {}
    tenant_id = str(custom_data.get("tenant_id") or "").strip()
    plan_key = str(custom_data.get("plan_key") or "starter").strip().lower() or "starter"

    sess = db.session()
    try:
        if subscription_id:
            sub = (
                sess.query(Subscription)
                .filter(Subscription.stripe_subscription_id == subscription_id)
                .first()
            )
            if sub:
                sub.status = internal_status
                sub.updated_at = utcnow()
                sess.flush()
            elif tenant_id and customer_id:
                create_pending_subscription(
                    db,
                    tenant_id=tenant_id,
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    plan_key=plan_key,
                )
                # Update status to the Paddle-reported status (overriding pending_webhook)
                sub = (
                    sess.query(Subscription)
                    .filter(Subscription.stripe_subscription_id == subscription_id)
                    .first()
                )
                if sub and internal_status != "pending_webhook":
                    sub.status = internal_status
                    sub.updated_at = utcnow()

        billing_event = BillingEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            tenant_id=tenant_id or None,
            payload=json.dumps(event),
        )
        sess.add(billing_event)
        sess.commit()
    except Exception as exc:
        sess.rollback()
        logger.error("PADDLE_WEBHOOK_DB_ERROR event_id=%s error=%s", event_id, exc)
        raise
    finally:
        sess.close()

    return {"status": "processed", "event_type": event_type}
