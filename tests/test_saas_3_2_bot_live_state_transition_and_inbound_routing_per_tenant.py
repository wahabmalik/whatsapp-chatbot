"""
Story saas-3.2: Bot live state transition and inbound routing per tenant.

Acceptance criteria covered:
  AC-1: Evolution connection success event transitions tenant connection state to connected.
  AC-2: Inbound messages route by instance_name -> tenant_id.
  AC-3: Unknown/cross-tenant instance routing is rejected before processing.
  AC-4: Inbound processing enforces connected + entitled + active tenant guards.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models import ConnectionState, Subscription, Tenant, UsageCounter

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "global-fallback-instance",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key",
}


@pytest.fixture()
def saas_webhook_app(tmp_path):
    db_path = tmp_path / "saas_story_3_2.db"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    env = {
        **_BASE_ENV,
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
def client(saas_webhook_app):
    return saas_webhook_app.test_client()


def _seed_tenant_runtime(
    app,
    *,
    tenant_id: str,
    instance_name: str,
    tenant_active: bool = True,
    subscription_status: str = "active",
    connection_status: str = "connected",
    usage_blocked: bool = False,
):
    db = app.extensions["saas_db"]
    sess = db.session()
    try:
        now = datetime.now(timezone.utc)

        tenant = sess.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
        if tenant is None:
            tenant = Tenant(id=tenant_id, name=f"tenant-{tenant_id[:8]}", is_active=tenant_active)
            sess.add(tenant)
        else:
            tenant.is_active = tenant_active

        conn = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one_or_none()
        if conn is None:
            conn = ConnectionState(
                tenant_id=tenant_id,
                status=connection_status,
                evolution_instance=instance_name,
                connected_at=now if connection_status == "connected" else None,
            )
            sess.add(conn)
        else:
            conn.status = connection_status
            conn.evolution_instance = instance_name
            conn.connected_at = now if connection_status == "connected" else None

        sub = sess.query(Subscription).filter(Subscription.tenant_id == tenant_id).one_or_none()
        if sub is None:
            sub = Subscription(
                tenant_id=tenant_id,
                stripe_customer_id=f"cus_{tenant_id[:8]}",
                stripe_subscription_id=f"sub_{tenant_id[:8]}",
                plan_key="starter",
                status=subscription_status,
                conversation_limit=2000,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            sess.add(sub)
        else:
            sub.status = subscription_status
            sub.plan_key = "starter"
            sub.conversation_limit = 2000
            sub.current_period_start = now
            sub.current_period_end = now + timedelta(days=30)

        usage = sess.query(UsageCounter).filter(UsageCounter.tenant_id == tenant_id).one_or_none()
        if usage is None:
            usage = UsageCounter(
                tenant_id=tenant_id,
                period_start=now,
                conversations_used=0,
                is_blocked=usage_blocked,
            )
            sess.add(usage)
        else:
            usage.is_blocked = usage_blocked

        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _evolution_message_payload(*, instance_name: str, message_id: str = "msg-1", text: str = "hello") -> dict:
    return {
        "event": "messages.upsert",
        "instance": instance_name,
        "data": {
            "instanceName": instance_name,
            "key": {
                "id": message_id,
                "fromMe": False,
                "remoteJid": "15551234567@s.whatsapp.net",
            },
            "message": {
                "conversation": text,
            },
            "pushName": "Customer",
            "messageTimestamp": "1714500000",
        },
    }


def test_state_transition_marks_connected_and_sets_connected_at(saas_webhook_app, client):
    tenant_id = "tenant-state-1"
    instance_name = "tenant-state-instance"
    _seed_tenant_runtime(
        saas_webhook_app,
        tenant_id=tenant_id,
        instance_name=instance_name,
        connection_status="connecting",
    )

    payload = {
        "event": "instance.state.updated",
        "data": {
            "instanceName": instance_name,
            "state": "open",
            "phone": "15559876543",
        },
    }

    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    db = saas_webhook_app.extensions["saas_db"]
    sess = db.session()
    try:
        row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one()
        assert row.status == "connected"
        assert row.connected_at is not None
        assert row.phone_number == "15559876543"
    finally:
        sess.close()


def test_inbound_message_routes_by_instance_to_tenant_and_processes(saas_webhook_app, client):
    tenant_id = "tenant-route-1"
    instance_name = "tenant-route-instance"
    _seed_tenant_runtime(
        saas_webhook_app,
        tenant_id=tenant_id,
        instance_name=instance_name,
        tenant_active=True,
        subscription_status="active",
        connection_status="connected",
        usage_blocked=False,
    )

    payload = _evolution_message_payload(instance_name=instance_name, message_id="msg-route-1")

    with patch(
        "app.views.process_whatsapp_message",
        return_value={
            "from": "15551234567",
            "message_id": "msg-route-1",
            "agent": "Ops",
            "input_text": "hello",
            "reply_text": "hi",
            "status": "sent",
            "error": None,
            "operator_review_flagged": False,
            "operator_review_reason": None,
            "evolution_instance": instance_name,
        },
    ) as mock_process:
        resp = client.post("/webhook", json=payload)

    assert resp.status_code == 200
    assert mock_process.call_count == 1
    inbound = mock_process.call_args.kwargs["inbound_message"]
    assert inbound["tenant_id"] == tenant_id
    assert inbound["evolution_instance"] == instance_name


def test_unknown_instance_is_rejected_and_not_processed(saas_webhook_app, client):
    _seed_tenant_runtime(
        saas_webhook_app,
        tenant_id="tenant-a",
        instance_name="known-instance",
    )

    payload = _evolution_message_payload(instance_name="unknown-instance", message_id="msg-unknown")

    with patch("app.views.process_whatsapp_message") as mock_process:
        resp = client.post("/webhook", json=payload)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["reason"] == "unknown_instance_name"
    assert mock_process.call_count == 0


def test_inbound_is_blocked_when_connection_not_connected(saas_webhook_app, client):
    tenant_id = "tenant-guard-1"
    instance_name = "tenant-guard-instance"
    _seed_tenant_runtime(
        saas_webhook_app,
        tenant_id=tenant_id,
        instance_name=instance_name,
        connection_status="connecting",
    )

    payload = _evolution_message_payload(instance_name=instance_name, message_id="msg-guard-1")

    with patch("app.views.process_whatsapp_message") as mock_process:
        resp = client.post("/webhook", json=payload)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["reason"] == "connection_not_connected"
    assert mock_process.call_count == 0


def test_inbound_is_blocked_when_tenant_inactive(saas_webhook_app, client):
    tenant_id = "tenant-guard-2"
    instance_name = "tenant-inactive-instance"
    _seed_tenant_runtime(
        saas_webhook_app,
        tenant_id=tenant_id,
        instance_name=instance_name,
        tenant_active=False,
        subscription_status="active",
        connection_status="connected",
    )

    payload = _evolution_message_payload(instance_name=instance_name, message_id="msg-guard-2")

    with patch("app.views.process_whatsapp_message") as mock_process:
        resp = client.post("/webhook", json=payload)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["reason"] == "tenant_inactive"
    assert mock_process.call_count == 0


def test_inbound_is_blocked_when_subscription_not_entitled(saas_webhook_app, client):
    tenant_id = "tenant-guard-3"
    instance_name = "tenant-sub-inactive-instance"
    _seed_tenant_runtime(
        saas_webhook_app,
        tenant_id=tenant_id,
        instance_name=instance_name,
        tenant_active=True,
        subscription_status="past_due",
        connection_status="connected",
    )

    payload = _evolution_message_payload(instance_name=instance_name, message_id="msg-guard-3")

    with patch("app.views.process_whatsapp_message") as mock_process:
        resp = client.post("/webhook", json=payload)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["reason"] == "subscription_not_entitled"
    assert mock_process.call_count == 0
