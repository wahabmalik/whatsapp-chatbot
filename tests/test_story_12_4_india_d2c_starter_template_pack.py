from __future__ import annotations

import os

import pytest

from app.models import StarterTemplateDraft
from app.services.auth_service import AUTH_SESSION_TENANT_KEY, AUTH_SESSION_USER_KEY, AuthIdentity, create_account
from app.services.starter_pack import get_starter_pack_catalogue

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "global-fallback-instance",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key",
    "INDIA_D2C_STARTER_PACK_ENABLED": "true",
    "INDIA_D2C_STARTER_PACK_COHORT_PERCENT": "100",
}


@pytest.fixture()
def starter_pack_app(tmp_path):
    db_path = tmp_path / "story_12_4.db"
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
def client(starter_pack_app):
    return starter_pack_app.test_client()


def _new_identity(app, email: str) -> AuthIdentity:
    db = app.extensions["saas_db"]
    return create_account(db, email=email, password="StrongPass!123")


def _login(client, identity: AuthIdentity, csrf_token: str = "csrf-12-4"):
    with client.session_transaction() as sess:
        sess[AUTH_SESSION_USER_KEY] = identity.user_id
        sess[AUTH_SESSION_TENANT_KEY] = identity.tenant_id
        sess["_csrf_token"] = csrf_token


def _enable_pack(client, *, replace_existing: bool = False):
    return client.post(
        "/onboarding/starter-pack/enable",
        data={
            "replace_existing": "true" if replace_existing else "false",
            "csrf_token": "csrf-12-4",
        },
        headers={"X-CSRFToken": "csrf-12-4"},
    )


def test_catalogue_integrity_is_fixed_and_complete():
    catalogue = get_starter_pack_catalogue()
    assert len(catalogue) == 4

    slugs = [row["workflow_slug"] for row in catalogue]
    assert sorted(slugs) == sorted(
        [
            "abandoned_cart_reminder",
            "order_status_update",
            "cod_confirmation",
            "support_triage",
        ]
    )
    assert len(set(slugs)) == 4
    assert all(row["category_label"] for row in catalogue)


def test_enablement_is_tenant_scoped_and_idempotent(starter_pack_app, client):
    tenant_a = _new_identity(starter_pack_app, "story12a@example.com")
    tenant_b = _new_identity(starter_pack_app, "story12b@example.com")

    _login(client, tenant_a)
    first = _enable_pack(client)
    assert first.status_code == 200
    first_payload = first.get_json()
    assert first_payload["summary"]["created"] == 4

    second = _enable_pack(client)
    assert second.status_code == 200
    second_payload = second.get_json()
    assert second_payload["summary"]["created"] == 0
    assert second_payload["summary"]["reused"] == 4

    status_a = client.get("/onboarding/starter-pack/status")
    assert status_a.status_code == 200
    assert len(status_a.get_json()["starter_pack_drafts"]) == 4

    client_b = starter_pack_app.test_client()
    _login(client_b, tenant_b)
    status_b = client_b.get("/onboarding/starter-pack/status")
    assert status_b.status_code == 200
    assert len(status_b.get_json()["starter_pack_drafts"]) == 0

    db = starter_pack_app.extensions["saas_db"]
    sess = db.session()
    try:
        count_a = sess.query(StarterTemplateDraft).filter(StarterTemplateDraft.tenant_id == tenant_a.tenant_id).count()
        count_b = sess.query(StarterTemplateDraft).filter(StarterTemplateDraft.tenant_id == tenant_b.tenant_id).count()
        assert count_a == 4
        assert count_b == 0
    finally:
        sess.close()


def test_replace_requires_explicit_confirmation(starter_pack_app, client):
    identity = _new_identity(starter_pack_app, "story12replace@example.com")
    _login(client, identity)

    initial = _enable_pack(client)
    assert initial.status_code == 200

    update = client.post(
        "/onboarding/starter-pack/draft/abandoned_cart_reminder/update",
        data={
            "csrf_token": "csrf-12-4",
            "title": "Custom Cart Follow-up",
            "body": "My edited operator copy",
            "category_label": "MARKETING",
        },
        headers={"X-CSRFToken": "csrf-12-4"},
    )
    assert update.status_code == 200

    no_replace = _enable_pack(client, replace_existing=False)
    assert no_replace.status_code == 200
    assert no_replace.get_json()["summary"]["reused"] == 4

    status_after_reuse = client.get("/onboarding/starter-pack/status").get_json()
    edited = [
        row for row in status_after_reuse["starter_pack_drafts"]
        if row["workflow_slug"] == "abandoned_cart_reminder"
    ][0]
    assert edited["title"] == "Custom Cart Follow-up"

    replace = _enable_pack(client, replace_existing=True)
    assert replace.status_code == 200
    assert replace.get_json()["summary"]["replaced"] == 4

    status_after_replace = client.get("/onboarding/starter-pack/status").get_json()
    replaced = [
        row for row in status_after_replace["starter_pack_drafts"]
        if row["workflow_slug"] == "abandoned_cart_reminder"
    ][0]
    assert replaced["title"] == "Abandoned Cart Follow-up"


def test_submit_and_activate_do_not_bypass_controls(starter_pack_app, client):
    identity = _new_identity(starter_pack_app, "story12controls@example.com")
    _login(client, identity)
    assert _enable_pack(client).status_code == 200

    blocked_submit = client.post(
        "/onboarding/starter-pack/draft/order_status_update/submit",
        data={"csrf_token": "csrf-12-4"},
        headers={"X-CSRFToken": "csrf-12-4"},
    )
    assert blocked_submit.status_code == 409
    assert blocked_submit.get_json()["blocked_reason"] == "consent_required"

    db = starter_pack_app.extensions["saas_db"]
    sess = db.session()
    try:
        row = (
            sess.query(StarterTemplateDraft)
            .filter(
                StarterTemplateDraft.tenant_id == identity.tenant_id,
                StarterTemplateDraft.workflow_slug == "order_status_update",
            )
            .one()
        )
        row.consent_state = "granted"
        row.provider_state = "draft"
        row.sendability_state = "blocked"
        sess.commit()
    finally:
        sess.close()

    allowed_submit = client.post(
        "/onboarding/starter-pack/draft/order_status_update/submit",
        data={"csrf_token": "csrf-12-4"},
        headers={"X-CSRFToken": "csrf-12-4"},
    )
    assert allowed_submit.status_code == 200
    assert allowed_submit.get_json()["draft"]["provider_state"] == "pending_approval"

    blocked_activate = client.post(
        "/onboarding/starter-pack/draft/order_status_update/activate",
        data={"csrf_token": "csrf-12-4", "recipient_count": "1"},
        headers={"X-CSRFToken": "csrf-12-4"},
    )
    assert blocked_activate.status_code == 409
    assert blocked_activate.get_json()["blocked_reason"] == "approval_required"

    sess = db.session()
    try:
        row = (
            sess.query(StarterTemplateDraft)
            .filter(
                StarterTemplateDraft.tenant_id == identity.tenant_id,
                StarterTemplateDraft.workflow_slug == "order_status_update",
            )
            .one()
        )
        row.provider_state = "approved"
        row.sendability_state = "blocked"
        sess.commit()
    finally:
        sess.close()

    blocked_sendability = client.post(
        "/onboarding/starter-pack/draft/order_status_update/activate",
        data={"csrf_token": "csrf-12-4", "recipient_count": "1"},
        headers={"X-CSRFToken": "csrf-12-4"},
    )
    assert blocked_sendability.status_code == 409
    assert blocked_sendability.get_json()["blocked_reason"] == "sendability_blocked"

    sess = db.session()
    try:
        row = (
            sess.query(StarterTemplateDraft)
            .filter(
                StarterTemplateDraft.tenant_id == identity.tenant_id,
                StarterTemplateDraft.workflow_slug == "order_status_update",
            )
            .one()
        )
        row.sendability_state = "ready"
        sess.commit()
    finally:
        sess.close()

    activated = client.post(
        "/onboarding/starter-pack/draft/order_status_update/activate",
        data={"csrf_token": "csrf-12-4", "recipient_count": "1"},
        headers={"X-CSRFToken": "csrf-12-4"},
    )
    assert activated.status_code == 200
    assert activated.get_json()["draft"]["draft_status"] == "active"


def test_enable_endpoint_surfaces_partial_failure_with_correlation(starter_pack_app, client, monkeypatch):
    identity = _new_identity(starter_pack_app, "story12fail@example.com")
    _login(client, identity)

    def _fake_enable(*_args, **_kwargs):
        return {
            "pack_key": "india_d2c_starter_pack",
            "pack_label": "India D2C starter pack",
            "created": [],
            "reused": [],
            "replaced": [],
            "failures": [
                {
                    "workflow_slug": "support_triage",
                    "message": "Draft creation failed. Retry this workflow from the starter-pack panel.",
                    "error": "db write failure",
                }
            ],
            "summary": {"created": 0, "reused": 0, "replaced": 0, "failed": 1},
            "correlation_id": "corr-story-12-4",
        }

    monkeypatch.setattr("app.onboarding.routes.enable_starter_pack", _fake_enable)

    response = _enable_pack(client)
    assert response.status_code == 207
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["summary"]["failed"] == 1
    assert payload["failures"][0]["workflow_slug"] == "support_triage"
    assert payload["correlation_id"] == "corr-story-12-4"
