from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from app.models import AuditLog, StarterTemplateDraft
from app.services.auth_service import AUTH_SESSION_TENANT_KEY, AUTH_SESSION_USER_KEY, AuthIdentity, create_account
from app.services import starter_pack as starter_pack_service

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
    "INDIA_MESSAGE_COST_MAX_RECIPIENT_COUNT": "1000",
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


def _activate(client, workflow_slug: str, **fields):
    data = {"csrf_token": "csrf-12-5", **fields}
    return client.post(
        f"/onboarding/starter-pack/draft/{workflow_slug}/activate",
        data=data,
        headers={"X-CSRFToken": "csrf-12-5"},
    )


def _latest_activate_audit(app, tenant_id: str) -> dict:
    db = app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(AuditLog)
            .filter(AuditLog.tenant_id == tenant_id, AuditLog.action == "starter_pack.activate")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert row is not None
        return json.loads(row.payload)
    finally:
        sess.close()


def _latest_telemetry(app) -> dict:
    path = Path(app.config["STARTER_PACK_TELEMETRY_PATH"])
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    return json.loads(lines[-1])


def test_preview_estimate_is_india_only_and_recalculates_when_inputs_change(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-preview@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="order_status_update")

    first = _activate(client, "order_status_update", recipient_count="2", preview_only="true")
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
    second = _activate(client, "order_status_update", recipient_count="3", preview_only="true")
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

    blocked = _activate(client, "abandoned_cart_reminder", recipient_count="2")
    assert blocked.status_code == 409
    blocked_payload = blocked.get_json()
    assert blocked_payload["blocked_reason"] == "cost_confirmation_required"
    assert blocked_payload["confirmation_required"] is True
    assert blocked_payload["estimate"]["projected_spend_paisa"] == 150
    assert blocked_payload["estimate"]["threshold_exceeded"] is True
    assert blocked_payload["estimate"]["operator_confirmation_decision"] == "required"

    confirmed = _activate(
        client,
        "abandoned_cart_reminder",
        recipient_count="2",
        explicit_cost_confirmation="true",
    )
    assert confirmed.status_code == 200
    confirmed_payload = confirmed.get_json()
    assert confirmed_payload["draft"]["draft_status"] == "active"
    assert confirmed_payload["estimate"]["operator_confirmation_decision"] == "confirmed"

    last_payload = _latest_activate_audit(cost_guardrail_app, identity.tenant_id)
    assert last_payload["category_label"] == "MARKETING"
    assert last_payload["recipient_count"] == 2
    assert last_payload["projected_spend_paisa"] == 150
    assert last_payload["threshold_exceeded"] is True
    assert last_payload["operator_confirmation_decision"] == "confirmed"
    assert last_payload["correlation_id"]


def test_activation_fails_closed_when_estimate_inputs_are_missing_and_writes_telemetry(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-failclosed@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="support_triage")

    response = _activate(client, "support_triage")
    assert response.status_code == 422
    payload = response.get_json()
    assert payload["blocked_reason"] == "estimation_failed"
    assert "Recipient count is required" in payload["message"]
    assert payload["draft"]["draft_status"] != "active"
    assert set(payload.keys()) >= {
        "ok",
        "message",
        "blocked_reason",
        "draft",
        "estimate",
    }

    last_event = _latest_telemetry(cost_guardrail_app)
    assert last_event["event_type"] == "starter_pack.activate"
    assert last_event["blocked_reason"] == "estimation_failed"
    assert last_event["operator_confirmation_decision"] == "estimation_failed"
    assert last_event["estimation_error"] == "Recipient count is required before send confirmation."


def test_threshold_equality_requires_confirmation(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-threshold-eq@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(
        cost_guardrail_app,
        tenant_id=identity.tenant_id,
        workflow_slug="order_status_update",
        category_label="UTILITY",
    )

    # UTILITY 20 paisa * 5 recipients = 100 == warning threshold
    blocked = _activate(client, "order_status_update", recipient_count="5")
    assert blocked.status_code == 409
    payload = blocked.get_json()
    assert payload["blocked_reason"] == "cost_confirmation_required"
    assert payload["confirmation_required"] is True
    assert payload["estimate"]["projected_spend_paisa"] == 100
    assert payload["estimate"]["threshold_exceeded"] is True
    assert "meets or exceeds" in payload["message"]


def test_non_integer_recipient_count_fails_closed(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-nonint@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="support_triage")

    response = _activate(client, "support_triage", recipient_count="2.9")
    assert response.status_code == 422
    payload = response.get_json()
    assert payload["blocked_reason"] == "estimation_failed"
    assert "positive integer" in payload["message"]
    assert payload["draft"]["draft_status"] != "active"
    assert payload["estimate"]["projected_spend_paisa"] is None


def test_non_finite_recipient_count_fails_closed(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-inf@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="support_triage")

    response = _activate(client, "support_triage", recipient_count="inf")
    assert response.status_code == 422
    payload = response.get_json()
    assert payload["blocked_reason"] == "estimation_failed"
    assert payload["draft"]["draft_status"] != "active"


def test_recipient_count_upper_bound_fails_closed(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-max@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="support_triage")

    response = _activate(client, "support_triage", recipient_count="1001")
    assert response.status_code == 422
    payload = response.get_json()
    assert payload["blocked_reason"] == "estimation_failed"
    assert "at most 1000" in payload["message"]


def test_unknown_category_fails_closed_and_persists_recipient_count(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-unknown-cat@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(
        cost_guardrail_app,
        tenant_id=identity.tenant_id,
        workflow_slug="support_triage",
        category_label="SERVICE",
    )

    response = _activate(client, "support_triage", recipient_count="4")
    assert response.status_code == 422
    payload = response.get_json()
    assert payload["blocked_reason"] == "estimation_failed"
    assert payload["estimate"]["inputs"]["recipient_count"] == 4
    assert payload["estimate"]["projected_spend_paisa"] is None

    audit = _latest_activate_audit(cost_guardrail_app, identity.tenant_id)
    assert audit["recipient_count"] == 4
    assert audit["estimation_error"]
    assert audit["blocked_reason"] == "estimation_failed"

    telemetry = _latest_telemetry(cost_guardrail_app)
    assert telemetry["recipient_count"] == 4
    assert telemetry["blocked_reason"] == "estimation_failed"


def test_non_india_price_table_fails_closed(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-nonin@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(cost_guardrail_app, tenant_id=identity.tenant_id, workflow_slug="support_triage")
    cost_guardrail_app.config["INDIA_MESSAGE_COST_COUNTRY"] = "US"

    response = _activate(client, "support_triage", recipient_count="2")
    assert response.status_code == 422
    payload = response.get_json()
    assert payload["blocked_reason"] == "estimation_failed"
    assert "India-only" in payload["message"]
    assert payload["estimate"]["inputs"]["recipient_count"] == 2
    assert payload["draft"]["draft_status"] != "active"


def test_preview_allowed_before_sendability_ready(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-preview-early@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200

    response = _activate(
        client,
        "order_status_update",
        recipient_count="2",
        preview_only="true",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["preview_only"] is True
    assert payload["estimate"]["projected_spend_paisa"] == 40
    assert payload["draft"]["draft_status"] != "active"
    assert payload["draft"]["sendability_state"] != "ready"


def test_category_label_allowlist_on_draft_update(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-allowlist@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200

    rejected = client.post(
        "/onboarding/starter-pack/draft/abandoned_cart_reminder/update",
        data={
            "csrf_token": "csrf-12-5",
            "title": "Abandoned Cart Follow-up",
            "body": "Hi there",
            "category_label": "SERVICE",
        },
        headers={"X-CSRFToken": "csrf-12-5"},
    )
    assert rejected.status_code == 400
    rejected_payload = rejected.get_json()
    assert rejected_payload["blocked_reason"] == "invalid_category_label"

    accepted = client.post(
        "/onboarding/starter-pack/draft/abandoned_cart_reminder/update",
        data={
            "csrf_token": "csrf-12-5",
            "title": "Abandoned Cart Follow-up",
            "body": "Hi there",
            "category_label": "UTILITY",
        },
        headers={"X-CSRFToken": "csrf-12-5"},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["draft"]["category_label"] == "UTILITY"


def test_telemetry_io_failure_does_not_roll_back_activation(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-telemetry@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(
        cost_guardrail_app,
        tenant_id=identity.tenant_id,
        workflow_slug="order_status_update",
        category_label="UTILITY",
    )

    with mock.patch.object(
        starter_pack_service.Path,
        "open",
        side_effect=OSError("disk full"),
    ):
        response = _activate(client, "order_status_update", recipient_count="1")

    assert response.status_code == 200
    assert response.get_json()["draft"]["draft_status"] == "active"
    audit = _latest_activate_audit(cost_guardrail_app, identity.tenant_id)
    assert audit["outcome"] == "activated"
    assert audit["recipient_count"] == 1


def test_operator_ui_surfaces_estimate_and_confirmation_controls(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-ui@example.com")
    _login(client, identity)
    assert client.get("/operator/access").status_code in {200, 302}

    dashboard = client.get("/operator")
    assert dashboard.status_code == 200
    dashboard_html = dashboard.get_data(as_text=True)
    assert "starter_pack_cost_guardrails.js" in dashboard_html
    assert "data-starter-pack-panel" in dashboard_html
    assert "StarterPackCostGuardrails" in dashboard_html or "data-starter-preview" in dashboard_html

    onboarding = client.get("/onboarding")
    assert onboarding.status_code == 200
    onboarding_html = onboarding.get_data(as_text=True)
    assert "starter_pack_cost_guardrails.js" in onboarding_html
    assert "starter-pack" in onboarding_html
    assert "StarterPackCostGuardrails" in onboarding_html

    js_path = Path(cost_guardrail_app.root_path) / "static" / "js" / "starter_pack_cost_guardrails.js"
    js_source = js_path.read_text(encoding="utf-8")
    assert "preview_only" in js_source
    assert "explicit_cost_confirmation" in js_source
    assert "India-only projected spend" in js_source
    assert "Confirm estimate and activate" in js_source
    assert "data-starter-recipient-count" in js_source


def test_blocked_send_contracts_are_stable(cost_guardrail_app, client):
    identity = _new_identity(cost_guardrail_app, "story125-contract@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200
    _mark_ready(
        cost_guardrail_app,
        tenant_id=identity.tenant_id,
        workflow_slug="abandoned_cart_reminder",
    )

    estimation_failed = _activate(client, "abandoned_cart_reminder", recipient_count="abc")
    assert estimation_failed.status_code == 422
    failed_payload = estimation_failed.get_json()
    assert failed_payload["ok"] is False
    assert failed_payload["blocked_reason"] == "estimation_failed"
    assert isinstance(failed_payload["message"], str) and failed_payload["message"]
    assert "estimate" in failed_payload
    assert "draft" in failed_payload

    confirmation = _activate(client, "abandoned_cart_reminder", recipient_count="2")
    assert confirmation.status_code == 409
    confirm_payload = confirmation.get_json()
    assert confirm_payload["ok"] is False
    assert confirm_payload["blocked_reason"] == "cost_confirmation_required"
    assert confirm_payload["confirmation_required"] is True
    assert confirm_payload["estimate"]["threshold_exceeded"] is True
    assert confirm_payload["estimate"]["inputs"]["recipient_count"] == 2
