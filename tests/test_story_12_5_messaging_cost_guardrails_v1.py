from __future__ import annotations

import json
import os

import pytest

from app.models import AuditLog, StarterTemplateDraft
from app.services.auth_service import AUTH_SESSION_TENANT_KEY, AUTH_SESSION_USER_KEY, AuthIdentity, create_account

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "global-fallback-instance",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key",
    "INDIA_D2C_STARTER_PACK_ENABLED": "true",
    "INDIA_D2C_STARTER_PACK_COHORT_PERCENT": "100",
    "INDIA_MESSAGE_COST_MARKETING_PAISA": "75",
    "INDIA_MESSAGE_COST_UTILITY_PAISA": "20",
    "INDIA_MESSAGE_COST_AUTHENTICATION_PAISA": "15",
    "INDIA_MESSAGE_COST_WARNING_THRESHOLD_PAISA": "100",
}


@pytest.fixture()
def cost_guardrail_app(tmp_path):
    db_path = tmp_path / "story_12_5.db"
    session_dir = tmp_path / "sessions"
    telemetry_path = tmp_path / "starter_pack_telemetry.jsonl"
    session_dir.mkdir()

    env = {
        **_BASE_ENV,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "SESSION_FILE_DIR": str(session_dir),
        "STARTER_PACK_TELEMETRY_PATH": str(telemetry_path),
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
def client(cost_guardrail_app):
    return cost_guardrail_app.test_client()


def _new_identity(app, email: str) -> AuthIdentity:
    db = app.extensions["saas_db"]
    return create_account(db, email=email, password="StrongPass!123")


def _login(client, identity: AuthIdentity, csrf_token: str = "csrf-12-5"):
    with client.session_transaction() as sess:
        sess[AUTH_SESSION_USER_KEY] = identity.user_id
        sess[AUTH_SESSION_TENANT_KEY] = identity.tenant_id
        sess["_csrf_token"] = csrf_token


def _enable_pack(client):
    return client.post(
        "/onboarding/starter-pack/enable",
        data={"replace_existing": "false", "csrf_token": "csrf-12-5"},
        headers={"X-CSRFToken": "csrf-12-5"},
    )


def _mark_ready(app, *, tenant_id: str, workflow_slug: str, category_label: str | None = None):
    db = app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(StarterTemplateDraft)
            .filter(
                StarterTemplateDraft.tenant_id == tenant_id,
                StarterTemplateDraft.workflow_slug == workflow_slug,
            )
            .one()
        )
        row.consent_state = "granted"
        row.provider_state = "approved"
        row.sendability_state = "ready"
        if category_label is not None:
            row.category_label = category_label
        sess.commit()
    finally:
        sess.close()


def test_preview_estimate_is_india_only_and_recalculates_when_inputs_change(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-preview@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="order_status_update")

    first = client.post(
        "/onboarding/starter-pack/draft/order_status_update/activate",
        data={
            "csrf_token": "csrf-12-5",
            "recipient_count": "2",
            "preview_only": "true",
        },
        headers={"X-CSRFToken": "csrf-12-5"},
    )
    assert first.status_code == 200
    first_payload = first.get_json()
    assert first_payload["preview_only"] is True
    assert first_payload["estimate"]["country_code"] == "IN"
    assert first_payload["estimate"]["price_table_scope"] == "india_only"
    assert first_payload["estimate"]["inputs"] == {
        "template_category": "UTILITY",
        "recipient_count": 2,
    }
    assert first_payload["estimate"]["projected_spend_paisa"] == 40

    _mark_ready(
        cost_guardrail_app,
        tenant_id=identity.tenant_id,
        workflow_slug="order_status_update",
        category_label="MARKETING",
    )
    second = client.post(
        "/onboarding/starter-pack/draft/order_status_update/activate",
        data={
            "csrf_token": "csrf-12-5",
            "recipient_count": "3",
            "preview_only": "true",
        },
        headers={"X-CSRFToken": "csrf-12-5"},
    )
    assert second.status_code == 200
    second_payload = second.get_json()
    assert second_payload["estimate"]["inputs"] == {
        "template_category": "MARKETING",
        "recipient_count": 3,
    }
    assert second_payload["estimate"]["projected_spend_paisa"] == 225


def test_above_threshold_activation_requires_explicit_confirmation_and_tags_audit(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-threshold@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(
        cost_guardrail_app,
        tenant_id=identity.tenant_id,
        workflow_slug="abandoned_cart_reminder",
    )

    blocked = client.post(
        "/onboarding/starter-pack/draft/abandoned_cart_reminder/activate",
        data={
            "csrf_token": "csrf-12-5",
            "recipient_count": "2",
        },
        headers={"X-CSRFToken": "csrf-12-5"},
    )
    assert blocked.status_code == 409
    blocked_payload = blocked.get_json()
    assert blocked_payload["blocked_reason"] == "cost_confirmation_required"
    assert blocked_payload["confirmation_required"] is True
    assert blocked_payload["estimate"]["projected_spend_paisa"] == 150
    assert blocked_payload["estimate"]["threshold_exceeded"] is True
    assert blocked_payload["estimate"]["operator_confirmation_decision"] == "required"

    confirmed = client.post(
        "/onboarding/starter-pack/draft/abandoned_cart_reminder/activate",
        data={
            "csrf_token": "csrf-12-5",
            "recipient_count": "2",
            "explicit_cost_confirmation": "true",
        },
        headers={"X-CSRFToken": "csrf-12-5"},
    )
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.get_json()
    assert confirmed_payload["draft"]["draft_status"] == "active"
    assert confirmed_payload["estimate"]["operator_confirmation_decision"] == "confirmed"

    db = cost_guardrail_app.extensions["saas_db"]
    sess = db.session()
    try:
        audit_rows = (
            sess.query(AuditLog)
            .filter(AuditLog.tenant_id == identity.tenant_id, AuditLog.action == "starter_pack.activate")
            .order_by(AuditLog.created_at.asc())
            .all()
        )
        assert len(audit_rows) >= 2
        last_payload = json.loads(audit_rows[-1].payload)
        assert last_payload["category_label"] == "MARKETING"
        assert last_payload["recipient_count"] == 2
        assert last_payload["projected_spend_paisa"] == 150
        assert last_payload["threshold_exceeded"] is True
        assert last_payload["operator_confirmation_decision"] == "confirmed"
        assert last_payload["correlation_id"]
    finally:
        sess.close()


def test_activation_fails_closed_when_estimate_inputs_are_missing_and_writes_telemetry(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-failclosed@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="support_triage")

    response = client.post(
        "/onboarding/starter-pack/draft/support_triage/activate",
        data={"csrf_token": "csrf-12-5"},
        headers={"X-CSRFToken": "csrf-12-5"},
    )
    assert response.status_code == 422
    payload = response.get_json()
    assert payload["blocked_reason"] == "estimation_failed"
    assert "Recipient count is required" in payload["message"]
    assert payload["draft"]["draft_status"] != "active"

    telemetry_path = cost_guardrail_app.config["STARTER_PACK_TELEMETRY_PATH"]
    lines = [line for line in open(telemetry_path, encoding="utf-8").read().splitlines() if line.strip()]
    assert lines
    last_event = json.loads(lines[-1])
    assert last_event["event_type"] == "starter_pack.activate"
    assert last_event["blocked_reason"] == "estimation_failed"
    assert last_event["operator_confirmation_decision"] == "estimation_failed"
    assert last_event["estimation_error"] == "Recipient count is required before send confirmation."