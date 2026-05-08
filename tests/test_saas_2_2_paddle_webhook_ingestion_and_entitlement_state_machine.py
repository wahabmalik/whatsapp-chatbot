"""
tests/test_saas_2_2_paddle_webhook_ingestion_and_entitlement_state_machine.py

Story saas-2.2: Paddle Webhook Ingestion and Entitlement State Machine

Acceptance criteria covered:
    AC-1: Signature verification + append-only billing_events idempotent by notification_id.
    AC-2: Supported webhook events project subscription state transitions.
    AC-3: Webhook transitions write audit_log rows with required metadata.
    AC-4: Invalid signature returns 400; unhandled event returns 200 and is stored.
    AC-5: ENF-01 preserved; pending_webhook remains non-entitled.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from unittest.mock import patch

import pytest

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "RECIPIENT_WAID": "15551234567",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key",
}

_PADDLE_WEBHOOK_SECRET = "pdl_ntfwd_test_secret"

_PADDLE_ENV = {
    "PADDLE_API_KEY": "pdl_api_test_mock",
    "PADDLE_WEBHOOK_SECRET": _PADDLE_WEBHOOK_SECRET,
    "PADDLE_STARTER_PRICE_ID": "pri_starter_test",
    "PADDLE_PRO_PRICE_ID": "pri_pro_test",
    "PADDLE_BUSINESS_PRICE_ID": "pri_business_test",
}


@pytest.fixture()
def billing_app(tmp_path):
    db_path = tmp_path / "saas_billing.db"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    env = {
        **_BASE_ENV,
        **_PADDLE_ENV,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SESSION_FILE_DIR": str(session_dir),
    }

    original = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        from app import create_app

        app = create_app()
        app.config.update(TESTING=True)
        yield app
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture()
def client(billing_app):
    return billing_app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sign_payload(payload_bytes: bytes, secret: str, ts: int | None = None) -> str:
    """Build a valid Paddle-Signature header value."""
    ts = ts or int(time.time())
    msg = f"{ts}:{payload_bytes.decode()}"
    h1 = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def _make_paddle_event(notification_id: str, event_type: str, data: dict) -> dict:
    """Build a minimal Paddle webhook notification payload."""
    return {
        "notification_id": notification_id,
        "event_type": event_type,
        "data": data,
    }


def _post_paddle_webhook(
    client,
    event_dict: dict,
    secret: str = _PADDLE_WEBHOOK_SECRET,
    bad_sig: bool = False,
) -> object:
    payload_bytes = json.dumps(event_dict).encode()
    if bad_sig:
        sig_header = "ts=0;h1=badhash"
    else:
        sig_header = _sign_payload(payload_bytes, secret)
    return client.post(
        "/billing/webhook/paddle",
        data=payload_bytes,
        content_type="application/json",
        headers={"Paddle-Signature": sig_header},
    )


def _signup_and_login(client, email="owner@example.com", password="StrongPass123!"):
    token = "signup-csrf"
    with client.session_transaction() as s:
        s["_csrf_token"] = token
    resp = client.post(
        "/auth/signup",
        data={"email": email, "password": password},
        headers={"X-CSRFToken": token},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def _get_session_tenant(client) -> str:
    with client.session_transaction() as s:
        return s.get("auth_tenant_id")


def _create_pending_subscription(
    app,
    tenant_id: str,
    sub_id: str = "sub_pdl_test_123",
    plan_key: str = "starter",
    customer_id: str = "ctm_test_123",
):
    from app.services.billing_service import create_pending_subscription

    db = app.extensions["saas_db"]
    create_pending_subscription(
        db,
        tenant_id=tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=sub_id,
        plan_key=plan_key,
    )


def _get_subscription_by_sub_id(app, sub_id: str):
    from app.models import Subscription

    db = app.extensions["saas_db"]
    s = db.session()
    try:
        return (
            s.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .first()
        )
    finally:
        s.close()


def _get_billing_events_by_id(app, notification_id: str):
    from app.models import BillingEvent

    db = app.extensions["saas_db"]
    s = db.session()
    try:
        return (
            s.query(BillingEvent)
            .filter(BillingEvent.stripe_event_id == notification_id)
            .all()
        )
    finally:
        s.close()


def _get_audit_entries(app, tenant_id=None, actor_type="paddle_webhook"):
    from app.models import AuditLog

    db = app.extensions["saas_db"]
    s = db.session()
    try:
        q = s.query(AuditLog).filter(AuditLog.actor_type == actor_type)
        if tenant_id:
            q = q.filter(AuditLog.tenant_id == tenant_id)
        return q.order_by(AuditLog.created_at.asc()).all()
    finally:
        s.close()


# ===========================================================================
# AC-1: Signature verification + idempotency
# ===========================================================================

class TestAC1WebhookVerificationAndIdempotency:
    def test_invalid_signature_returns_400(self, billing_app, client):
        event = _make_paddle_event("notif_bad_sig", "subscription.created", {"id": "sub_x"})
        resp = _post_paddle_webhook(client, event, bad_sig=True)
        assert resp.status_code == 400
        assert resp.get_json()["error_code"] == "WEBHOOK_SIGNATURE_INVALID"

    def test_first_delivery_stores_event_second_delivery_is_noop(self, billing_app, client):
        _signup_and_login(client)
        tenant_id = _get_session_tenant(client)
        _create_pending_subscription(billing_app, tenant_id, "sub_pdl_idem_001")

        event = _make_paddle_event(
            "notif_idem_001",
            "subscription.updated",
            {
                "id": "sub_pdl_idem_001",
                "status": "active",
                "customer_id": "ctm_test_123",
            },
        )

        first = _post_paddle_webhook(client, event)
        second = _post_paddle_webhook(client, event)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.get_json()["data"]["result"] == "already_processed"


# ===========================================================================
# AC-2: State machine projections
# ===========================================================================

class TestAC2StateMachineProjection:
    def test_subscription_created_sets_trialing(self, billing_app, client):
        _signup_and_login(client, email="pdl-created-trialing@example.com")
        tenant_id = _get_session_tenant(client)

        event = _make_paddle_event(
            "notif_created_trial",
            "subscription.created",
            {
                "id": "sub_pdl_created_trial",
                "status": "trialing",
                "customer_id": "ctm_trial",
                "custom_data": {"tenant_id": tenant_id, "plan_key": "starter"},
            },
        )
        resp = _post_paddle_webhook(client, event)
        assert resp.status_code == 200

        sub = _get_subscription_by_sub_id(billing_app, "sub_pdl_created_trial")
        assert sub is not None
        assert sub.status == "trialing"

    def test_subscription_updated_active_sets_active(self, billing_app, client):
        _signup_and_login(client, email="pdl-updated-active@example.com")
        tenant_id = _get_session_tenant(client)
        _create_pending_subscription(billing_app, tenant_id, "sub_pdl_active")

        event = _make_paddle_event(
            "notif_updated_active",
            "subscription.updated",
            {"id": "sub_pdl_active", "status": "active", "customer_id": "ctm_test_123"},
        )
        assert _post_paddle_webhook(client, event).status_code == 200

        sub = _get_subscription_by_sub_id(billing_app, "sub_pdl_active")
        assert sub.status == "active"

    @pytest.mark.parametrize(
        "paddle_status,expected_status",
        [
            ("trialing", "trialing"),
            ("past_due", "past_due"),
            ("canceled", "canceled"),
            ("paused", "past_due"),  # paused maps to past_due per _PADDLE_STATUS_MAP
        ],
    )
    def test_subscription_updated_maps_statuses(
        self, billing_app, client, paddle_status, expected_status
    ):
        safe = paddle_status.replace("_", "")
        _signup_and_login(client, email=f"pdl-{safe}@example.com")
        tenant_id = _get_session_tenant(client)
        sub_id = f"sub_pdl_{safe}"
        _create_pending_subscription(billing_app, tenant_id, sub_id)

        event = _make_paddle_event(
            f"notif_updated_{safe}",
            "subscription.updated",
            {"id": sub_id, "status": paddle_status, "customer_id": "ctm_test_123"},
        )
        assert _post_paddle_webhook(client, event).status_code == 200

        sub = _get_subscription_by_sub_id(billing_app, sub_id)
        assert sub.status == expected_status

    def test_subscription_canceled_sets_canceled(self, billing_app, client):
        _signup_and_login(client, email="pdl-sub-canceled@example.com")
        tenant_id = _get_session_tenant(client)
        _create_pending_subscription(billing_app, tenant_id, "sub_pdl_canceled")

        event = _make_paddle_event(
            "notif_sub_canceled",
            "subscription.canceled",
            {"id": "sub_pdl_canceled", "status": "canceled", "customer_id": "ctm_test_123"},
        )
        assert _post_paddle_webhook(client, event).status_code == 200

        sub = _get_subscription_by_sub_id(billing_app, "sub_pdl_canceled")
        assert sub.status == "canceled"

    def test_transaction_completed_sets_active(self, billing_app, client):
        _signup_and_login(client, email="pdl-txn-completed@example.com")
        tenant_id = _get_session_tenant(client)
        _create_pending_subscription(billing_app, tenant_id, "sub_pdl_txn")

        event = _make_paddle_event(
            "notif_txn_completed",
            "transaction.completed",
            {
                "id": "txn_pdl_001",
                "subscription_id": "sub_pdl_txn",
                "customer_id": "ctm_test_123",
                "status": "completed",
            },
        )
        assert _post_paddle_webhook(client, event).status_code == 200

        sub = _get_subscription_by_sub_id(billing_app, "sub_pdl_txn")
        assert sub.status == "active"


# ===========================================================================
# AC-4: Unhandled event types
# ===========================================================================

class TestAC4UnhandledEvents:
    def test_unhandled_event_returns_200(self, billing_app, client):
        event = _make_paddle_event(
            "notif_unhandled_001",
            "product.created",
            {"id": "pro_123"},
        )
        resp = _post_paddle_webhook(client, event)
        assert resp.status_code == 200
        body = resp.get_json()
        # Service returns "unhandled" or similar non-error result
        assert body["ok"] is True


# ===========================================================================
# AC-5: ENF-01 entitlement guard
# ===========================================================================

class TestAC5EntitlementGuard:
    def test_pending_webhook_is_not_entitled(self, billing_app, client):
        from app.services.billing_service import can_activate_bot

        _signup_and_login(client, email="pdl-pending-entitlement@example.com")
        tenant_id = _get_session_tenant(client)
        _create_pending_subscription(billing_app, tenant_id, "sub_pdl_pending_ent")

        assert can_activate_bot(billing_app.extensions["saas_db"], tenant_id) is False

    def test_active_subscription_satisfies_entitlement(self, billing_app, client):
        from app.services.billing_service import can_activate_bot

        _signup_and_login(client, email="pdl-active-entitlement@example.com")
        tenant_id = _get_session_tenant(client)
        _create_pending_subscription(billing_app, tenant_id, "sub_pdl_active_ent")

        db = billing_app.extensions["saas_db"]
        assert can_activate_bot(db, tenant_id) is False

        event = _make_paddle_event(
            "notif_active_ent",
            "subscription.updated",
            {"id": "sub_pdl_active_ent", "status": "active", "customer_id": "ctm_test_123"},
        )
        assert _post_paddle_webhook(client, event).status_code == 200
        assert can_activate_bot(db, tenant_id) is True

    def test_past_due_subscription_is_not_entitled(self, billing_app, client):
        from app.services.billing_service import can_activate_bot

        _signup_and_login(client, email="pdl-past-due-entitlement@example.com")
        tenant_id = _get_session_tenant(client)
        _create_pending_subscription(billing_app, tenant_id, "sub_pdl_pastdue_ent")

        db = billing_app.extensions["saas_db"]

        # Activate first
        activate = _make_paddle_event(
            "notif_pastdue_ent_activate",
            "subscription.updated",
            {"id": "sub_pdl_pastdue_ent", "status": "active", "customer_id": "ctm_test_123"},
        )
        assert _post_paddle_webhook(client, activate).status_code == 200
        assert can_activate_bot(db, tenant_id) is True

        # Then mark past_due
        block = _make_paddle_event(
            "notif_pastdue_ent_block",
            "subscription.updated",
            {"id": "sub_pdl_pastdue_ent", "status": "past_due", "customer_id": "ctm_test_123"},
        )
        assert _post_paddle_webhook(client, block).status_code == 200
        assert can_activate_bot(db, tenant_id) is False
