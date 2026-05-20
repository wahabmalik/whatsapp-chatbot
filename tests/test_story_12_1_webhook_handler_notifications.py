from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import BillingEvent, Subscription, TenantNotification
from app.services.auth_service import create_account
from app.services.webhook_handler import ingest_webhook_event

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "instance-story-12-1-webhook",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "story-12-1-webhook-secret",
    "USAGE_ALERT_THRESHOLD_PCTS": "50,80",
}


@pytest.fixture()
def webhook_app(tmp_path):
    db_path = tmp_path / "story_12_1_webhook.db"
    session_dir = tmp_path / "sessions"
    analytics_store_path = tmp_path / "conversation_analytics_events.jsonl"
    session_dir.mkdir()

    env = {
        **_BASE_ENV,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SESSION_FILE_DIR": str(session_dir),
        "ANALYTICS_EVENT_STORE_PATH": str(analytics_store_path),
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


def _tenant_id(app, email: str) -> str:
    identity = create_account(app.extensions["saas_db"], email=email, password="StrongPass!121")
    return identity.tenant_id


def _upsert_subscription(app, *, tenant_id: str, sub_id: str, status: str = "active"):
    db = app.extensions["saas_db"]
    sess = db.session()
    try:
        now = datetime.now(timezone.utc)
        row = (
            sess.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .one_or_none()
        )
        if row is None:
            row = Subscription(
                tenant_id=tenant_id,
                stripe_customer_id=f"cus_{tenant_id[:8]}",
                stripe_subscription_id=sub_id,
                plan_key="starter",
                status=status,
                conversation_limit=10,
                current_period_start=now - timedelta(days=3),
                current_period_end=now + timedelta(days=27),
            )
            sess.add(row)
        else:
            row.status = status
        sess.commit()
    finally:
        sess.close()


def _mock_stripe_event(monkeypatch, event: dict):
    import stripe

    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda payload, sig, secret: event,
    )


def test_invoice_payment_failed_creates_notification_without_metadata(webhook_app, monkeypatch):
    tenant_id = _tenant_id(webhook_app, "story121-webhook-missing-meta-payment@example.com")
    sub_id = "sub_story_121_missing_meta_payment"
    _upsert_subscription(webhook_app, tenant_id=tenant_id, sub_id=sub_id, status="active")

    event = {
        "id": "evt_story_121_missing_meta_payment",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_story_121",
                "subscription": sub_id,
                "customer": "cus_story_121",
                "status": "open",
            }
        },
    }
    _mock_stripe_event(monkeypatch, event)

    status_code, result = ingest_webhook_event(
        webhook_app.extensions["saas_db"],
        b"{}",
        "sig_test",
        "whsec_test",
    )

    assert status_code == 200
    assert result == "ok"

    db = webhook_app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.tenant_id == tenant_id,
                TenantNotification.alert_type == "payment_failed",
            )
            .one_or_none()
        )
        assert row is not None
    finally:
        sess.close()


def test_subscription_updated_creates_trial_notification_without_metadata(webhook_app, monkeypatch):
    tenant_id = _tenant_id(webhook_app, "story121-webhook-missing-meta-trial@example.com")
    sub_id = "sub_story_121_missing_meta_trial"
    _upsert_subscription(webhook_app, tenant_id=tenant_id, sub_id=sub_id, status="active")

    period_end = int((datetime.now(timezone.utc) + timedelta(hours=23)).timestamp())
    event = {
        "id": "evt_story_121_missing_meta_trial",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": sub_id,
                "status": "trialing",
                "current_period_end": period_end,
                "customer": "cus_story_121",
            }
        },
    }
    _mock_stripe_event(monkeypatch, event)

    status_code, result = ingest_webhook_event(
        webhook_app.extensions["saas_db"],
        b"{}",
        "sig_test",
        "whsec_test",
    )

    assert status_code == 200
    assert result == "ok"

    db = webhook_app.extensions["saas_db"]
    sess = db.session()
    try:
        rows = (
            sess.query(TenantNotification)
            .filter(TenantNotification.tenant_id == tenant_id)
            .all()
        )
        alert_types = {row.alert_type for row in rows}
        assert "trial_expiry_1d" in alert_types
    finally:
        sess.close()


def test_webhook_rolls_back_when_notification_creation_fails(webhook_app, monkeypatch):
    tenant_id = _tenant_id(webhook_app, "story121-webhook-graceful-degrade@example.com")
    sub_id = "sub_story_121_graceful"
    _upsert_subscription(webhook_app, tenant_id=tenant_id, sub_id=sub_id, status="active")

    event = {
        "id": "evt_story_121_graceful",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_story_121_graceful",
                "subscription": sub_id,
                "customer": "cus_story_121",
                "status": "open",
            }
        },
    }
    _mock_stripe_event(monkeypatch, event)

    def _raise(*args, **kwargs):
        raise RuntimeError("notification create failed")

    monkeypatch.setattr("app.services.webhook_handler.create_stripe_billing_notifications", _raise)

    with pytest.raises(RuntimeError, match="notification create failed"):
        ingest_webhook_event(
            webhook_app.extensions["saas_db"],
            b"{}",
            "sig_test",
            "whsec_test",
        )

    db = webhook_app.extensions["saas_db"]
    sess = db.session()
    try:
        billed_event = (
            sess.query(BillingEvent)
            .filter(BillingEvent.stripe_event_id == "evt_story_121_graceful")
            .one_or_none()
        )
        assert billed_event is None

        sub = (
            sess.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .one_or_none()
        )
        assert sub is not None
        assert sub.status == "active"
    finally:
        sess.close()
