from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import AuditLog, ConnectionState, TenantNotification
from app.services.notification_center import dismiss_tenant_notification
from app.services.auth_service import AUTH_SESSION_TENANT_KEY, AUTH_SESSION_USER_KEY, AuthIdentity, create_account
from app.services.reconnection_assistant import _steps_for_channel, sync_reconnection_notifications

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "story-12-3-instance",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "story-12-3-secret",
}

_CSRF = "csrf-12-3"


@pytest.fixture()
def reconnection_app(tmp_path):
    db_path = tmp_path / "story_12_3.db"
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    queue_path = tmp_path / "operator_review_queue.jsonl"

    env = {
        **_BASE_ENV,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SESSION_FILE_DIR": str(session_dir),
        "ESCALATION_QUEUE_PATH": str(queue_path),
        "RECONNECTION_MAX_RETRIES": "2",
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
def client(reconnection_app):
    return reconnection_app.test_client()


def _new_identity(app, email: str) -> AuthIdentity:
    db = app.extensions["saas_db"]
    return create_account(db, email=email, password="StrongPass!123")


def _login_operator(client, identity: AuthIdentity):
    with client.session_transaction() as sess:
        sess[AUTH_SESSION_USER_KEY] = identity.user_id
        sess[AUTH_SESSION_TENANT_KEY] = identity.tenant_id
        sess["dashboard_role"] = "operator"
        sess["_csrf_token"] = _CSRF


def _set_connection_state(app, *, tenant_id: str, status: str, updated_at: datetime | None = None):
    db = app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(ConnectionState)
            .filter(ConnectionState.tenant_id == tenant_id)
            .one()
        )
        row.status = status
        row.evolution_instance = row.evolution_instance or "tenant-test-instance"
        if updated_at is not None:
            row.updated_at = updated_at
        sess.commit()
    finally:
        sess.close()


def test_unit_step_catalog_includes_required_topics():
    keys = [step.key for step in _steps_for_channel("whatsapp")]
    assert keys == ["token", "network", "provider", "permissions"]


def test_disconnection_detection_creates_notification_with_clear_cta(reconnection_app, client):
    identity = _new_identity(reconnection_app, "story123-detect@example.com")
    _login_operator(client, identity)

    _set_connection_state(
        reconnection_app,
        tenant_id=identity.tenant_id,
        status="disconnected",
        updated_at=datetime.now(timezone.utc),
    )

    response = client.get("/api/notifications")

    assert response.status_code == 200
    payload = response.get_json()
    reconnection_rows = [
        item for item in payload["notifications"]
        if item["alert_type"] == "reconnection_required"
    ]
    assert len(reconnection_rows) == 1
    row = reconnection_rows[0]
    assert "Reconnect WhatsApp" in row["title"]
    assert row["details"]["flow_api"] == "/api/reconnection-assistant/flow"
    assert row["details"]["detected_within_window"] is True


def test_guided_flow_covers_required_steps_and_supports_retry(reconnection_app, client, monkeypatch):
    from app.onboarding import ConnectionSnapshot

    identity = _new_identity(reconnection_app, "story123-flow@example.com")
    _login_operator(client, identity)
    _set_connection_state(reconnection_app, tenant_id=identity.tenant_id, status="disconnected")

    flow = client.get("/api/reconnection-assistant/flow")
    assert flow.status_code == 200
    payload = flow.get_json()

    assert payload["degraded"] is True
    step_keys = [step["key"] for step in payload["steps"]]
    assert step_keys == ["token", "network", "provider", "permissions"]
    assert all(step["retry_available"] is True for step in payload["steps"])

    monkeypatch.setattr(
        "app.services.reconnection_assistant.sync_connection_status",
        lambda db, app, tenant_id: ConnectionSnapshot(status="disconnected", phone=None),
    )

    provider_retry = client.post(
        "/api/reconnection-assistant/steps/provider/retry",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert provider_retry.status_code == 200
    retry_payload = provider_retry.get_json()
    assert retry_payload["step_key"] == "provider"
    assert retry_payload["resolved"] is False
    assert retry_payload["status"] in {"disconnected", "degraded"}


def test_escalation_and_actions_are_logged(reconnection_app, client):
    identity = _new_identity(reconnection_app, "story123-escalate@example.com")
    _login_operator(client, identity)

    escalate = client.post(
        "/api/reconnection-assistant/escalate",
        data={"csrf_token": _CSRF, "reason": "manual_test"},
        headers={"X-CSRFToken": _CSRF},
    )
    assert escalate.status_code == 200
    payload = escalate.get_json()
    assert payload["escalated"] is True

    queue_path = reconnection_app.config["ESCALATION_QUEUE_PATH"]
    with open(queue_path, "r", encoding="utf-8") as file_obj:
        line = file_obj.readline().strip()
    row = json.loads(line)
    assert row["reason"] == "reconnection_assistant:manual_test"

    db = reconnection_app.extensions["saas_db"]
    sess = db.session()
    try:
        audit = (
            sess.query(AuditLog)
            .filter(
                AuditLog.tenant_id == identity.tenant_id,
                AuditLog.action == "reconnection_assistant.escalated",
            )
            .one_or_none()
        )
        assert audit is not None
    finally:
        sess.close()


def test_abandonment_is_logged_without_forced_escalation(reconnection_app, client):
    identity = _new_identity(reconnection_app, "story123-abandon@example.com")
    _login_operator(client, identity)

    abandon = client.post(
        "/api/reconnection-assistant/abandon",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert abandon.status_code == 200
    assert abandon.get_json()["abandoned"] is True

    db = reconnection_app.extensions["saas_db"]
    sess = db.session()
    try:
        abandoned = (
            sess.query(AuditLog)
            .filter(
                AuditLog.tenant_id == identity.tenant_id,
                AuditLog.action == "reconnection_assistant.abandoned",
            )
            .one_or_none()
        )
        escalated = (
            sess.query(AuditLog)
            .filter(
                AuditLog.tenant_id == identity.tenant_id,
                AuditLog.action == "reconnection_assistant.escalated",
            )
            .one_or_none()
        )
        assert abandoned is not None
        assert escalated is None
    finally:
        sess.close()


def test_multiple_failed_retries_recommend_escalation(reconnection_app, client, monkeypatch):
    from app.onboarding import ConnectionSnapshot

    identity = _new_identity(reconnection_app, "story123-retry@example.com")
    _login_operator(client, identity)
    _set_connection_state(reconnection_app, tenant_id=identity.tenant_id, status="disconnected")

    monkeypatch.setattr(
        "app.services.reconnection_assistant.sync_connection_status",
        lambda db, app, tenant_id: ConnectionSnapshot(status="disconnected", phone=None),
    )

    first = client.post(
        "/api/reconnection-assistant/steps/provider/retry",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    second = client.post(
        "/api/reconnection-assistant/steps/provider/retry",
        data={"csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["escalation_recommended"] is False
    assert second.get_json()["escalation_recommended"] is True

    db = reconnection_app.extensions["saas_db"]
    sess = db.session()
    try:
        notifications = (
            sess.query(TenantNotification)
            .filter(TenantNotification.tenant_id == identity.tenant_id)
            .all()
        )
        assert all(row.category in {"connectivity", "billing", "usage"} for row in notifications)
    finally:
        sess.close()


def test_telegram_flow_uses_provider_probe_and_reports_degraded(reconnection_app, client, monkeypatch):
    class _Response:
        status_code = 503

        @staticmethod
        def json():
            return {"ok": False}

    identity = _new_identity(reconnection_app, "story123-telegram-down@example.com")
    _login_operator(client, identity)

    reconnection_app.config["OUTBOUND_CHANNEL"] = "telegram"
    reconnection_app.config["TELEGRAM_BOT_TOKEN"] = "bot-token"
    reconnection_app.config["TELEGRAM_DEFAULT_CHAT_ID"] = "chat-id"

    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())

    response = client.get("/api/reconnection-assistant/flow")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["channel"] == "telegram"
    assert payload["degraded"] is True
    assert payload["diagnostics"]["status_source"] == "provider_probe"
    assert payload["diagnostics"]["provider_probe"] == "telegram_provider_http_503"


def test_telegram_flow_reports_connected_when_provider_probe_passes(reconnection_app, client, monkeypatch):
    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": {"id": 123}}

    identity = _new_identity(reconnection_app, "story123-telegram-ok@example.com")
    _login_operator(client, identity)

    reconnection_app.config["OUTBOUND_CHANNEL"] = "telegram"
    reconnection_app.config["TELEGRAM_BOT_TOKEN"] = "bot-token"
    reconnection_app.config["TELEGRAM_DEFAULT_CHAT_ID"] = "chat-id"

    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())

    response = client.get("/api/reconnection-assistant/flow")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["channel"] == "telegram"
    assert payload["degraded"] is False
    assert payload["status"] == "connected"
    assert payload["diagnostics"]["status_source"] == "provider_probe"
    assert payload["diagnostics"]["provider_probe"] == "telegram_provider_ok"


@pytest.mark.parametrize(
    ("channel", "connect_key", "outbound_key", "recipient_key", "probe_detail"),
    [
        (
            "instagram",
            "INSTAGRAM_CONNECT_URL",
            "INSTAGRAM_OUTBOUND_URL",
            "INSTAGRAM_DEFAULT_RECIPIENT_ID",
            "instagram_provider_http_503",
        ),
        (
            "messenger",
            "MESSENGER_CONNECT_URL",
            "MESSENGER_OUTBOUND_URL",
            "MESSENGER_DEFAULT_RECIPIENT_ID",
            "messenger_provider_http_503",
        ),
        (
            "tiktok",
            "TIKTOK_CONNECT_URL",
            "TIKTOK_OUTBOUND_URL",
            "TIKTOK_DEFAULT_RECIPIENT_ID",
            "tiktok_provider_http_503",
        ),
    ],
)
def test_social_channels_use_provider_probe_and_report_degraded(
    reconnection_app,
    client,
    monkeypatch,
    channel,
    connect_key,
    outbound_key,
    recipient_key,
    probe_detail,
):
    class _Response:
        status_code = 503

    identity = _new_identity(reconnection_app, f"story123-{channel}-down@example.com")
    _login_operator(client, identity)

    reconnection_app.config["OUTBOUND_CHANNEL"] = channel
    reconnection_app.config[connect_key] = "https://provider.example.test/health"
    reconnection_app.config[outbound_key] = "https://provider.example.test/send"
    reconnection_app.config[recipient_key] = "recipient-123"

    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())

    response = client.get("/api/reconnection-assistant/flow")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["channel"] == channel
    assert payload["degraded"] is True
    assert payload["diagnostics"]["status_source"] == "provider_probe"
    assert payload["diagnostics"]["provider_probe"] == probe_detail


@pytest.mark.parametrize(
    ("channel", "connect_key", "outbound_key", "recipient_key", "probe_detail"),
    [
        (
            "instagram",
            "INSTAGRAM_CONNECT_URL",
            "INSTAGRAM_OUTBOUND_URL",
            "INSTAGRAM_DEFAULT_RECIPIENT_ID",
            "instagram_provider_http_503",
        ),
        (
            "messenger",
            "MESSENGER_CONNECT_URL",
            "MESSENGER_OUTBOUND_URL",
            "MESSENGER_DEFAULT_RECIPIENT_ID",
            "messenger_provider_http_503",
        ),
        (
            "tiktok",
            "TIKTOK_CONNECT_URL",
            "TIKTOK_OUTBOUND_URL",
            "TIKTOK_DEFAULT_RECIPIENT_ID",
            "tiktok_provider_http_503",
        ),
    ],
)
def test_social_notifications_report_detection_window_as_first_observed(
    reconnection_app,
    monkeypatch,
    channel,
    connect_key,
    outbound_key,
    recipient_key,
    probe_detail,
):
    class _Response:
        status_code = 503

    identity = _new_identity(reconnection_app, f"story123-{channel}-notify@example.com")

    reconnection_app.config["OUTBOUND_CHANNEL"] = channel
    reconnection_app.config[connect_key] = "https://provider.example.test/health"
    reconnection_app.config[outbound_key] = "https://provider.example.test/send"
    reconnection_app.config[recipient_key] = "recipient-123"
    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())

    result = sync_reconnection_notifications(reconnection_app, reconnection_app.extensions["saas_db"], identity.tenant_id)

    assert result["detected"] is True
    assert result["detected_within_window"] is True

    db = reconnection_app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(TenantNotification)
            .filter(TenantNotification.tenant_id == identity.tenant_id)
            .one()
        )
        details = json.loads(row.details_json)
    finally:
        sess.close()

    assert details["channel"] == channel
    assert details["detected_within_window"] is True
    assert details["detected_within_window_source"] == "provider_probe.first_observed_at"
    assert details["diagnostics"]["status_source"] == "provider_probe"
    assert details["diagnostics"]["provider_probe"] == probe_detail


def test_degraded_notification_does_not_fan_out_across_minute_markers(reconnection_app, monkeypatch):
    class _Response:
        status_code = 503

    identity = _new_identity(reconnection_app, "story123-fanout@example.com")
    db = reconnection_app.extensions["saas_db"]

    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_CONNECT_URL"] = "https://provider.example.test/health"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["INSTAGRAM_DEFAULT_RECIPIENT_ID"] = "recipient-123"
    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())

    base = datetime(2026, 5, 18, 10, 0, 0, tzinfo=timezone.utc)
    first = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id, now=base)
    second = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id, now=base + timedelta(minutes=1, seconds=5))

    assert first["notification_created"] is True
    assert second["notification_created"] is False

    sess = db.session()
    try:
        rows = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.tenant_id == identity.tenant_id,
                TenantNotification.alert_type == "reconnection_required",
                TenantNotification.dismissed_at.is_(None),
            )
            .all()
        )
    finally:
        sess.close()

    assert len(rows) == 1


def test_social_notification_dismiss_then_recheck_reuses_marker(reconnection_app, monkeypatch):
    class _Response:
        status_code = 503

    identity = _new_identity(reconnection_app, "story123-dismiss-recheck@example.com")
    db = reconnection_app.extensions["saas_db"]

    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_CONNECT_URL"] = "https://provider.example.test/health"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["INSTAGRAM_DEFAULT_RECIPIENT_ID"] = "recipient-123"
    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())

    base = datetime.now(timezone.utc)
    first = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id, now=base)
    assert first["notification_created"] is True

    sess = db.session()
    try:
        row = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.tenant_id == identity.tenant_id,
                TenantNotification.alert_type == "reconnection_required",
            )
            .one()
        )
        notification_id = row.id
    finally:
        sess.close()

    dismissed = dismiss_tenant_notification(db, tenant_id=identity.tenant_id, notification_id=notification_id)
    assert dismissed is True

    second = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id, now=base + timedelta(minutes=1, seconds=5))
    assert second["detected"] is True
    assert second["notification_created"] is False

    sess = db.session()
    try:
        rows = (
            sess.query(TenantNotification)
            .filter(
                TenantNotification.tenant_id == identity.tenant_id,
                TenantNotification.alert_type == "reconnection_required",
            )
            .all()
        )
    finally:
        sess.close()

    assert len(rows) == 1


def test_sync_notifications_raises_on_active_lookup_error(reconnection_app, monkeypatch):
    class _Response:
        status_code = 503

    identity = _new_identity(reconnection_app, "story123-active-lookup-error@example.com")
    db = reconnection_app.extensions["saas_db"]

    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_CONNECT_URL"] = "https://provider.example.test/health"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["INSTAGRAM_DEFAULT_RECIPIENT_ID"] = "recipient-123"
    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())

    def _boom(*args, **kwargs):
        raise RuntimeError("lookup failure")

    monkeypatch.setattr("app.services.reconnection_assistant._find_active_reconnection_notification", _boom)

    with pytest.raises(RuntimeError, match="lookup failure"):
        sync_reconnection_notifications(reconnection_app, db, identity.tenant_id)


def test_channel_switch_mid_flow_uses_current_active_channel(reconnection_app, client, monkeypatch):
    class _Response:
        status_code = 503

    identity = _new_identity(reconnection_app, "story123-switch-channel@example.com")
    _login_operator(client, identity)

    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_CONNECT_URL"] = "https://provider.example.test/health"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["INSTAGRAM_DEFAULT_RECIPIENT_ID"] = "recipient-123"

    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())
    created = sync_reconnection_notifications(reconnection_app, reconnection_app.extensions["saas_db"], identity.tenant_id)
    assert created["detected"] is True

    reconnection_app.config["OUTBOUND_CHANNEL"] = "messenger"
    reconnection_app.config["MESSENGER_CONNECT_URL"] = "https://provider.example.test/health"
    reconnection_app.config["MESSENGER_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["MESSENGER_DEFAULT_RECIPIENT_ID"] = "recipient-abc"

    response = client.get("/api/reconnection-assistant/flow")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["channel"] == "messenger"


def test_flow_rejects_stale_expected_channel(reconnection_app, client):
    identity = _new_identity(reconnection_app, "story123-flow-stale-channel@example.com")
    _login_operator(client, identity)

    reconnection_app.config["OUTBOUND_CHANNEL"] = "messenger"
    response = client.get("/api/reconnection-assistant/flow?channel=instagram")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Channel changed" in payload["message"]


def test_retry_rejects_stale_expected_channel(reconnection_app, client):
    identity = _new_identity(reconnection_app, "story123-retry-stale-channel@example.com")
    _login_operator(client, identity)

    reconnection_app.config["OUTBOUND_CHANNEL"] = "messenger"
    response = client.post(
        "/api/reconnection-assistant/steps/provider/retry",
        data={"csrf_token": _CSRF, "channel": "instagram"},
        headers={"X-CSRFToken": _CSRF},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Channel changed" in payload["message"]


def test_network_retry_rejects_malformed_url(reconnection_app, client):
    identity = _new_identity(reconnection_app, "story123-network-malformed@example.com")
    _login_operator(client, identity)

    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://"

    response = client.post(
        "/api/reconnection-assistant/steps/network/retry",
        data={"csrf_token": _CSRF, "channel": "instagram"},
        headers={"X-CSRFToken": _CSRF},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["step_passed"] is False
    assert "must include scheme and host" in payload["detail"]


def test_whatsapp_connected_disconnected_connected_transition(reconnection_app):
    identity = _new_identity(reconnection_app, "story123-wa-transition@example.com")
    db = reconnection_app.extensions["saas_db"]
    now = datetime.now(timezone.utc)

    _set_connection_state(
        reconnection_app,
        tenant_id=identity.tenant_id,
        status="connected",
        updated_at=now,
    )
    first = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id, now=now)
    assert first["detected"] is False

    _set_connection_state(
        reconnection_app,
        tenant_id=identity.tenant_id,
        status="disconnected",
        updated_at=now + timedelta(seconds=20),
    )
    second = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id, now=now + timedelta(seconds=30))
    assert second["detected"] is True
    assert second["notification_created"] is True
    assert second["detected_within_window"] is True

    _set_connection_state(
        reconnection_app,
        tenant_id=identity.tenant_id,
        status="connected",
        updated_at=now + timedelta(seconds=50),
    )
    third = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id, now=now + timedelta(seconds=55))
    assert third["detected"] is False


def test_escalation_queue_write_failure_surfaces_queue_error(reconnection_app, client, monkeypatch):
    identity = _new_identity(reconnection_app, "story123-escalation-queue-error@example.com")
    _login_operator(client, identity)

    monkeypatch.setattr(
        "app.services.reconnection_assistant.append_review_artifact",
        lambda *a, **k: (False, "queue_write_failed"),
    )

    escalate = client.post(
        "/api/reconnection-assistant/escalate",
        data={"csrf_token": _CSRF, "reason": "manual_test"},
        headers={"X-CSRFToken": _CSRF},
    )
    assert escalate.status_code == 503
    payload = escalate.get_json()
    assert payload["ok"] is False
    assert payload["escalated"] is False
    assert payload["queue_written"] is False
    assert payload["queue_error"] == "queue_write_failed"

    db = reconnection_app.extensions["saas_db"]
    sess = db.session()
    try:
        audit = (
            sess.query(AuditLog)
            .filter(
                AuditLog.tenant_id == identity.tenant_id,
                AuditLog.action == "reconnection_assistant.escalation_failed",
            )
            .one_or_none()
        )
        assert audit is not None
        details = json.loads(audit.payload)
    finally:
        sess.close()

    assert details["queue_error"] == "queue_write_failed"
    assert details["queue_written"] is False


def test_dashboard_template_reconnection_actions_are_wired():
    dashboard_template = Path(__file__).resolve().parents[1] / "app" / "templates" / "dashboard.html"
    content = dashboard_template.read_text(encoding="utf-8")

    assert "[data-reconnection-open-flow]" in content
    assert "[data-reconnection-escalate]" in content
    assert "[data-reconnection-abandon]" in content

    assert "openButton.addEventListener('click', loadFlow);" in content
    assert "fetch('/api/reconnection-assistant/flow'" in content
    assert "postForm('/api/reconnection-assistant/steps/' + encodeURIComponent(step.key) + '/retry', {" in content
    assert "channel: activeFlowChannel || ''" in content
    assert "postForm('/api/reconnection-assistant/escalate', { reason: 'operator_requested' })" in content
    assert "postForm('/api/reconnection-assistant/abandon', {})" in content


def test_social_probe_timeout_malformed(monkeypatch, reconnection_app, client):
    class _Response:
        status_code = 200
        def json(self):
            return {"ok": True, "result": {"id": 123}}

    identity = _new_identity(reconnection_app, "story123-malformed-timeout@example.com")
    _login_operator(client, identity)
    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["INSTAGRAM_PROBE_TIMEOUT_SECONDS"] = "not_a_number"
    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())
    response = client.get("/api/reconnection-assistant/flow")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["channel"] == "instagram"
    assert payload["status"] == "connected"
    assert payload["degraded"] is False


def test_detection_window_malformed(monkeypatch, reconnection_app):
    class _Response:
        status_code = 503
    identity = _new_identity(reconnection_app, "story123-malformed-window@example.com")
    db = reconnection_app.extensions["saas_db"]
    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["INSTAGRAM_PROBE_TIMEOUT_SECONDS"] = 0.2
    reconnection_app.config["RECONNECTION_DETECTION_WINDOW_SECONDS"] = "bad"
    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())
    result = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id)
    assert result["detected"] is True
    assert result["detected_within_window"] is True


def test_marker_reuse_seconds_malformed(monkeypatch, reconnection_app):
    class _Response:
        status_code = 503
    identity = _new_identity(reconnection_app, "story123-malformed-marker@example.com")
    db = reconnection_app.extensions["saas_db"]
    reconnection_app.config["OUTBOUND_CHANNEL"] = "instagram"
    reconnection_app.config["INSTAGRAM_OUTBOUND_URL"] = "https://provider.example.test/send"
    reconnection_app.config["INSTAGRAM_PROBE_TIMEOUT_SECONDS"] = 0.2
    reconnection_app.config["RECONNECTION_NON_WHATSAPP_MARKER_REUSE_SECONDS"] = "bad"
    monkeypatch.setattr("app.services.reconnection_assistant.requests.get", lambda *a, **k: _Response())
    result = sync_reconnection_notifications(reconnection_app, db, identity.tenant_id)
    assert result["detected"] is True
    assert result["detected_within_window"] is True
