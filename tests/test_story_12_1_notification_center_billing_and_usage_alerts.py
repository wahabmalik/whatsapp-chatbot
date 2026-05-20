from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Subscription, TenantNotification
from app.services.auth_service import AUTH_SESSION_TENANT_KEY, AUTH_SESSION_USER_KEY, AuthIdentity, create_account
from app.services.billing_service import ingest_webhook_event
from app.services.conversation_analytics import emit_analytics_event

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "instance-story-12-1",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "story-12-1-secret",
    "USAGE_ALERT_THRESHOLD_PCTS": "50,80",
    "ANALYTICS_RETENTION_DAYS": "90",
}

_CSRF = "csrf-12-1"


@pytest.fixture()
def notification_app(tmp_path):
    db_path = tmp_path / "story_12_1.db"
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


@pytest.fixture()
def client(notification_app):
    return notification_app.test_client()


def _new_identity(app, email: str) -> AuthIdentity:
    db = app.extensions["saas_db"]
    return create_account(db, email=email, password="StrongPass!121")


def _login_operator(client, identity: AuthIdentity):
    with client.session_transaction() as sess:
        sess[AUTH_SESSION_USER_KEY] = identity.user_id
        sess[AUTH_SESSION_TENANT_KEY] = identity.tenant_id
        sess["dashboard_role"] = "operator"
        sess["_csrf_token"] = _CSRF


def _upsert_subscription(app, *, tenant_id: str, subscription_id: str, limit: int = 10, status: str = "active"):
    db = app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(Subscription)
            .filter(Subscription.stripe_subscription_id == subscription_id)
            .one_or_none()
        )
        now = datetime.now(timezone.utc)
        if row is None:
            row = Subscription(
                tenant_id=tenant_id,
                stripe_customer_id=f"cus_{tenant_id[:8]}",
                stripe_subscription_id=subscription_id,
                plan_key="starter",
                status=status,
                conversation_limit=limit,
                current_period_start=now - timedelta(days=3),
                current_period_end=now + timedelta(days=27),
            )
            sess.add(row)
        else:
            row.status = status
            row.conversation_limit = limit
            row.current_period_start = now - timedelta(days=3)
            row.current_period_end = now + timedelta(days=27)
        sess.commit()
    finally:
        sess.close()


def _payment_failed_event(
    tenant_id: str,
    *,
    event_id: str = "evt_payment_failed_121",
    subscription_id: str = "sub_story_121",
) -> dict:
    return {
        "id": event_id,
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_121",
                "subscription": subscription_id,
                "customer": "cus_story_121",
                "metadata": {
                    "tenant_id": tenant_id,
                    "plan_key": "starter",
                },
                "status": "open",
            }
        },
    }


def _trialing_event(
    tenant_id: str,
    *,
    event_id: str = "evt_trial_121",
    days_remaining: int = 1,
    subscription_id: str = "sub_story_121",
) -> dict:
    period_end = int((datetime.now(timezone.utc) + timedelta(days=days_remaining)).timestamp())
    return {
        "id": event_id,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": subscription_id,
                "subscription": subscription_id,
                "customer": "cus_story_121",
                "status": "trialing",
                "current_period_end": period_end,
                "metadata": {
                    "tenant_id": tenant_id,
                    "plan_key": "starter",
                },
            }
        },
    }


def _emit_usage_events(app, *, tenant_id: str, total: int):
    for idx in range(total):
        emit_analytics_event(
            app,
            stage="inbound_receive",
            correlation_id=f"corr-usage-{idx}",
            tenant_id=tenant_id,
            user_id=f"user-{idx}",
            conversation_id=f"conv-{idx}",
            outcome_status="received",
            details={"source": "test"},
        )


def test_notification_center_renders_trial_payment_and_usage_alerts(notification_app, client):
    identity = _new_identity(notification_app, "story121-panel@example.com")
    _login_operator(client, identity)

    _upsert_subscription(notification_app, tenant_id=identity.tenant_id, subscription_id="sub_story_121", limit=4)
    _emit_usage_events(notification_app, tenant_id=identity.tenant_id, total=2)
    # Seed usage alerts first while the test limit is 4.
    seeded_usage = client.get("/api/notifications")
    assert seeded_usage.status_code == 200
    ingest_webhook_event(
        notification_app.extensions["saas_db"],
        _payment_failed_event(identity.tenant_id, subscription_id="sub_story_121"),
        b"{}",
    )
    ingest_webhook_event(
        notification_app.extensions["saas_db"],
        _trialing_event(
            identity.tenant_id,
            event_id="evt_trial_121_a",
            days_remaining=1,
            subscription_id="sub_story_121",
        ),
        b"{}",
    )

    response = client.get("/operator")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Notification Center" in html
    assert "Payment failure detected" in html
    assert "Trial ends soon" in html
    assert "Trial expires in 24 hours" in html
    assert "Usage reached 50%" in html


def test_notifications_can_be_dismissed_individually_and_persist(notification_app, client):
    identity = _new_identity(notification_app, "story121-dismiss@example.com")
    _login_operator(client, identity)

    _upsert_subscription(notification_app, tenant_id=identity.tenant_id, subscription_id="sub_story_121_dismiss", limit=4)
    _emit_usage_events(notification_app, tenant_id=identity.tenant_id, total=2)
    seeded_usage = client.get("/api/notifications")
    assert seeded_usage.status_code == 200
    ingest_webhook_event(
        notification_app.extensions["saas_db"],
        _payment_failed_event(
            identity.tenant_id,
            event_id="evt_payment_failed_121_dismiss",
            subscription_id="sub_story_121_dismiss",
        ),
        b"{}",
    )

    all_notifications = client.get("/api/notifications").get_json()["notifications"]
    assert len(all_notifications) >= 2

    usage_row = next(item for item in all_notifications if item["alert_type"].startswith("usage_threshold_"))
    dismiss_response = client.post(
        f"/api/notifications/{usage_row['id']}/dismiss",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert dismiss_response.status_code == 200

    refreshed = client.get("/api/notifications").get_json()["notifications"]
    remaining_ids = {item["id"] for item in refreshed}
    assert usage_row["id"] not in remaining_ids

    html = client.get("/operator").get_data(as_text=True)
    assert "Usage reached 50%" not in html


def test_billing_alerts_are_created_by_webhook_events(notification_app):
    identity = _new_identity(notification_app, "story121-webhook@example.com")
    _upsert_subscription(notification_app, tenant_id=identity.tenant_id, subscription_id="sub_story_121_webhook", limit=10)

    result = ingest_webhook_event(
        notification_app.extensions["saas_db"],
        _payment_failed_event(identity.tenant_id, event_id="evt_payment_failed_121_webhook"),
        b"{}",
    )

    assert result["status"] == "processed"
    db = notification_app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.tenant_id == identity.tenant_id,
                TenantNotification.alert_type == "payment_failed",
            )
            .one_or_none()
        )
        assert row is not None
        assert row.dismissed_at is None
    finally:
        sess.close()


def test_usage_threshold_alerts_come_from_analytics_event_counts(notification_app, client):
    identity = _new_identity(notification_app, "story121-usage@example.com")
    other_identity = _new_identity(notification_app, "story121-usage-other@example.com")
    _login_operator(client, identity)

    _upsert_subscription(notification_app, tenant_id=identity.tenant_id, subscription_id="sub_story_121_usage", limit=4)
    _upsert_subscription(notification_app, tenant_id=other_identity.tenant_id, subscription_id="sub_story_121_usage_other", limit=4)

    _emit_usage_events(notification_app, tenant_id=identity.tenant_id, total=2)
    _emit_usage_events(notification_app, tenant_id=other_identity.tenant_id, total=4)

    response = client.get("/api/notifications")

    assert response.status_code == 200
    payload = response.get_json()
    usage_rows = [item for item in payload["notifications"] if item["alert_type"].startswith("usage_threshold_")]
    assert usage_rows
    details = usage_rows[0]["details"]
    assert details["conversations_used"] == 2
    assert details["conversation_limit"] == 4


def test_notification_center_is_tenant_isolated_for_list_and_dismiss(notification_app, client):
    identity_a = _new_identity(notification_app, "story121-isolation-a@example.com")
    identity_b = _new_identity(notification_app, "story121-isolation-b@example.com")

    _upsert_subscription(notification_app, tenant_id=identity_a.tenant_id, subscription_id="sub_story_121_iso_a", limit=4)
    _upsert_subscription(notification_app, tenant_id=identity_b.tenant_id, subscription_id="sub_story_121_iso_b", limit=4)

    ingest_webhook_event(
        notification_app.extensions["saas_db"],
        _payment_failed_event(identity_a.tenant_id, event_id="evt_payment_failed_121_iso_a"),
        b"{}",
    )
    ingest_webhook_event(
        notification_app.extensions["saas_db"],
        _payment_failed_event(identity_b.tenant_id, event_id="evt_payment_failed_121_iso_b"),
        b"{}",
    )

    _login_operator(client, identity_a)
    payload_a = client.get("/api/notifications").get_json()
    payment_rows_a = [item for item in payload_a["notifications"] if item["alert_type"] == "payment_failed"]
    assert len(payment_rows_a) == 1
    only_id = payment_rows_a[0]["id"]

    # Attempt to dismiss tenant B row while logged in as tenant A.
    db = notification_app.extensions["saas_db"]
    sess = db.session()
    try:
        other_row = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.tenant_id == identity_b.tenant_id,
                TenantNotification.alert_type == "payment_failed",
            )
            .one()
        )
        foreign_id = other_row.id
    finally:
        sess.close()

    forbidden = client.post(
        f"/api/notifications/{foreign_id}/dismiss",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert forbidden.status_code == 404

    still_present = client.get("/api/notifications").get_json()["notifications"]
    payment_rows_after = [item for item in still_present if item["alert_type"] == "payment_failed"]
    assert len(payment_rows_after) == 1
    assert payment_rows_after[0]["id"] == only_id


def test_notifications_api_requires_authenticated_identity(notification_app, client):
    with client.session_transaction() as sess:
        sess["dashboard_role"] = "operator"

    response = client.get("/api/notifications")
    assert response.status_code == 401
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Authentication required" in payload["message"]


def test_notifications_api_rejects_non_operator_role(notification_app, client):
    identity = _new_identity(notification_app, "story121-non-operator@example.com")
    with client.session_transaction() as sess:
        sess[AUTH_SESSION_USER_KEY] = identity.user_id
        sess[AUTH_SESSION_TENANT_KEY] = identity.tenant_id
        sess["dashboard_role"] = "end-user"

    response = client.get("/api/notifications")
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Operator access required" in payload["message"]


def test_dismiss_notification_rejects_invalid_identifier(notification_app, client):
    identity = _new_identity(notification_app, "story121-invalid-id@example.com")
    _login_operator(client, identity)

    response = client.post(
        "/api/notifications/not-a-uuid/dismiss",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Invalid notification identifier" in payload["message"]


def test_notifications_api_returns_json_500_when_list_fails(notification_app, client, monkeypatch):
    identity = _new_identity(notification_app, "story121-list-fail@example.com")
    _login_operator(client, identity)

    def _raise_list(*args, **kwargs):
        raise RuntimeError("db list failed")

    monkeypatch.setattr("app.views_dashboard.list_tenant_notifications", _raise_list)

    response = client.get("/api/notifications")
    assert response.status_code == 500
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Unable to fetch notifications" in payload["message"]


def test_dismiss_notification_returns_json_500_when_store_fails(notification_app, client, monkeypatch):
    identity = _new_identity(notification_app, "story121-dismiss-fail@example.com")
    _login_operator(client, identity)

    notification_id = "11111111-1111-4111-8111-111111111111"

    def _raise_dismiss(*args, **kwargs):
        raise RuntimeError("db dismiss failed")

    monkeypatch.setattr("app.views_dashboard.dismiss_tenant_notification", _raise_dismiss)

    response = client.post(
        f"/api/notifications/{notification_id}/dismiss",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert response.status_code == 500
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Unable to dismiss notification" in payload["message"]


def test_notifications_stable_with_malformed_reconnection_config(notification_app, client):
    identity = _new_identity(notification_app, "story121-malformed-reconnection@example.com")
    _login_operator(client, identity)
    # Set malformed reconnection config values
    notification_app.config["RECONNECTION_DETECTION_WINDOW_SECONDS"] = "not_a_number"
    notification_app.config["RECONNECTION_NON_WHATSAPP_MARKER_REUSE_SECONDS"] = "bad"
    notification_app.config["OUTBOUND_CHANNEL"] = "instagram"
    notification_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    notification_app.config["INSTAGRAM_PROBE_TIMEOUT_SECONDS"] = "not_a_number"
    # Should not error or 500
    response = client.get("/api/notifications")
    assert response.status_code == 200
    payload = response.get_json()
    assert "notifications" in payload


def test_notifications_api_gracefully_degrades_when_usage_sync_fails(notification_app, client, monkeypatch):
    identity = _new_identity(notification_app, "story121-analytics-unavailable@example.com")
    _login_operator(client, identity)
    _upsert_subscription(notification_app, tenant_id=identity.tenant_id, subscription_id="sub_story_121_analytics_fail", limit=4)

    def _raise_usage_sync(*args, **kwargs):
        raise RuntimeError("analytics unavailable")

    monkeypatch.setattr("app.views_dashboard.sync_usage_threshold_notifications", _raise_usage_sync)

    response = client.get("/api/notifications")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "notifications" in payload


def test_operator_dashboard_renders_within_performance_budget(notification_app, client):
    identity = _new_identity(notification_app, "story121-performance@example.com")
    _login_operator(client, identity)

    _upsert_subscription(notification_app, tenant_id=identity.tenant_id, subscription_id="sub_story_121_perf", limit=4)
    _emit_usage_events(notification_app, tenant_id=identity.tenant_id, total=2)
    seed_response = client.get("/api/notifications")
    assert seed_response.status_code == 200

    start = time.perf_counter()
    response = client.get("/operator")
    elapsed_seconds = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed_seconds <= 2.0
