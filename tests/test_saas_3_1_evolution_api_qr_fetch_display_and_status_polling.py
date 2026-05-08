"""
Story saas-3.1: Evolution API QR Fetch, Display, and Status Polling

Acceptance criteria covered:
  AC-1: GET /onboarding/qr-code returns QR image using tenant-specific instance.
  AC-2: Missing connection_states row is provisioned with unique instance_name.
  AC-3: GET /onboarding/status-stream emits SSE status events.
  AC-4: QR refresh/fetch failure returns retryable EVOLUTION_UNAVAILABLE (503).
  AC-5: Non-entitled tenant gets NO_ACTIVE_SUBSCRIPTION (402).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "global-fallback-instance",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key",
}


@pytest.fixture()
def onboarding_app(tmp_path):
    db_path = tmp_path / "saas_onboarding.db"
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
        app.config["ONBOARDING_STATUS_STREAM_INTERVAL_SECONDS"] = 0
        app.config["ONBOARDING_STATUS_STREAM_MAX_EVENTS"] = 1
        app.config["ONBOARDING_QR_BACKOFF_SECONDS"] = 0
        yield app
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture()
def client(onboarding_app):
    return onboarding_app.test_client()


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


def _set_subscription_status(app, tenant_id: str, status: str = "active"):
    from app.models import Subscription

    db = app.extensions["saas_db"]
    sess = db.session()
    try:
        now = datetime.now(timezone.utc)
        existing = (
            sess.query(Subscription)
            .filter(Subscription.tenant_id == tenant_id)
            .first()
        )
        if existing is None:
            existing = Subscription(
                tenant_id=tenant_id,
                stripe_customer_id="cus_test_onboarding",
                stripe_subscription_id=f"sub_{tenant_id[:8]}",
                plan_key="starter",
                status=status,
                conversation_limit=2000,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            sess.add(existing)
        else:
            existing.status = status
            existing.plan_key = "starter"
            existing.conversation_limit = 2000
            existing.current_period_start = now
            existing.current_period_end = now + timedelta(days=30)
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


class TestStory31QrFetch:
    def test_onboarding_page_requires_auth(self, client):
        resp = client.get("/onboarding", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_qr_code_rejects_non_entitled_tenant(self, client):
        _signup_and_login(client, email="no-sub@example.com")
        resp = client.get("/onboarding/qr-code")
        assert resp.status_code == 402
        payload = resp.get_json()
        assert payload["error_code"] == "NO_ACTIVE_SUBSCRIPTION"

    def test_qr_code_fetch_uses_tenant_instance_and_returns_data_uri(self, onboarding_app, client, monkeypatch):
        _signup_and_login(client, email="active@example.com")
        tenant_id = _get_session_tenant(client)
        _set_subscription_status(onboarding_app, tenant_id, status="active")

        post_mock = MagicMock()
        post_mock.status_code = 201
        post_mock.content = b"{}"
        post_mock.json.return_value = {}

        get_mock = MagicMock()
        get_mock.status_code = 200
        get_mock.content = b"{\"base64\":\"ZmFrZXFy\",\"expires_in_seconds\":60}"
        get_mock.json.return_value = {"base64": "ZmFrZXFy", "expires_in_seconds": 60}

        monkeypatch.setattr("app.onboarding.service.requests.post", lambda *a, **k: post_mock)
        monkeypatch.setattr("app.onboarding.service.requests.get", lambda *a, **k: get_mock)

        resp = client.get("/onboarding/qr-code")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["ok"] is True
        assert payload["data"]["qr_image"].startswith("data:image/png;base64,")
        assert payload["data"]["expires_in_seconds"] == 60
        assert payload["data"]["instance_name"].startswith("tenant-")

    def test_qr_fetch_provisions_connection_state_when_missing(self, onboarding_app, client, monkeypatch):
        from app.models import ConnectionState

        _signup_and_login(client, email="missing-state@example.com")
        tenant_id = _get_session_tenant(client)
        _set_subscription_status(onboarding_app, tenant_id, status="active")

        db = onboarding_app.extensions["saas_db"]
        sess = db.session()
        try:
            sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).delete()
            sess.commit()
        finally:
            sess.close()

        post_mock = MagicMock(status_code=201, content=b"{}")
        post_mock.json.return_value = {}
        get_mock = MagicMock(status_code=200, content=b"{\"base64\":\"ZmFrZQ==\"}")
        get_mock.json.return_value = {"base64": "ZmFrZQ=="}

        monkeypatch.setattr("app.onboarding.service.requests.post", lambda *a, **k: post_mock)
        monkeypatch.setattr("app.onboarding.service.requests.get", lambda *a, **k: get_mock)

        resp = client.get("/onboarding/qr-code")
        assert resp.status_code == 200

        sess = db.session()
        try:
            row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one_or_none()
            assert row is not None
            assert row.evolution_instance
        finally:
            sess.close()

    def test_qr_fetch_returns_503_when_evolution_unavailable(self, onboarding_app, client, monkeypatch):
        _signup_and_login(client, email="evo-down@example.com")
        tenant_id = _get_session_tenant(client)
        _set_subscription_status(onboarding_app, tenant_id, status="active")

        def _raise(*_a, **_k):
            raise RuntimeError("evolution down")

        monkeypatch.setattr("app.onboarding.service.requests.post", _raise)

        resp = client.get("/onboarding/qr-code")
        assert resp.status_code == 503
        payload = resp.get_json()
        assert payload["error_code"] == "EVOLUTION_UNAVAILABLE"


class TestStory31StatusStream:
    def test_status_stream_returns_sse_payload(self, onboarding_app, client, monkeypatch):
        from app.onboarding import ConnectionSnapshot

        _signup_and_login(client, email="stream@example.com")
        tenant_id = _get_session_tenant(client)
        _set_subscription_status(onboarding_app, tenant_id, status="active")

        monkeypatch.setattr(
            "app.onboarding.routes.sync_connection_status",
            lambda db, app, tenant: ConnectionSnapshot(status="connected", phone="923001112223"),
        )

        resp = client.get("/onboarding/status-stream")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("text/event-stream")

        body = resp.data.decode("utf-8")
        assert "\"status\": \"connected\"" in body
        assert "923001112223" in body

    def test_status_stream_requires_auth(self, client):
        resp = client.get("/onboarding/status-stream", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
