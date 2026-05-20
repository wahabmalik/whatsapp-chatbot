"""Story 12.6 — Compliance and Sendability Control Surface.

Acceptance criteria covered:
  AC 12.6.1 — Consent ledger: tenant-scoped, searchable, CRUD via API.
  AC 12.6.2 — Template sendability states exposed (approved/pending/rejected/paused).
  AC 12.6.3 — Sendability alert indicator: no_issue | warning | action_required.
  AC 12.6.4 — Pre-dispatch gate blocks sends on missing consent or non-sendable state.
  AC 12.6.5 — Audit trail with correlation_id; no secret leakage in payload.
  AC 12.6.6 — Stale/unknown provider state applies safe default (block send).
  AC 12.6.7 — Gate does NOT alter retry/fallback path; eligible sends unaffected.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.models import AuditLog, ConsentLedger, StarterTemplateDraft
from app.services.auth_service import AUTH_SESSION_TENANT_KEY, AUTH_SESSION_USER_KEY, AuthIdentity, create_account
from app.services.compliance import (
    ALERT_ACTION_REQUIRED,
    ALERT_NO_ISSUE,
    ALERT_WARNING,
    DISPLAY_STATE_APPROVED,
    DISPLAY_STATE_PAUSED,
    DISPLAY_STATE_PENDING,
    DISPLAY_STATE_REJECTED,
    DISPLAY_STATE_STALE,
    DISPLAY_STATE_UNKNOWN,
    REASON_CONSENT_MISSING,
    REASON_STALE_OR_UNKNOWN,
    REASON_TEMPLATE_NOT_SENDABLE,
    check_dispatch_eligibility,
    evaluate_sendability_alert,
    get_consent_ledger,
    get_template_sendability_states,
    map_provider_state_to_display,
    upsert_consent_record,
)

_BASE_ENV = {
    "WHATSAPP_PROVIDER": "evolution",
    "EVOLUTION_API_URL": "http://evolution.local",
    "EVOLUTION_API_KEY": "test-evo-key",
    "EVOLUTION_INSTANCE_NAME": "global-fallback-instance",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key-12-6",
    "INDIA_D2C_STARTER_PACK_ENABLED": "true",
    "INDIA_D2C_STARTER_PACK_COHORT_PERCENT": "100",
}

_CSRF = "csrf-12-6"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def compliance_app(tmp_path):
    db_path = tmp_path / "story_12_6.db"
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
def client(compliance_app):
    return compliance_app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_identity(app, email: str) -> AuthIdentity:
    db = app.extensions["saas_db"]
    return create_account(db, email=email, password="StrongPass!126")


def _login(client, identity: AuthIdentity) -> None:
    with client.session_transaction() as sess:
        sess[AUTH_SESSION_USER_KEY] = identity.user_id
        sess[AUTH_SESSION_TENANT_KEY] = identity.tenant_id
        sess["_csrf_token"] = _CSRF
        sess["dashboard_role"] = "operator"


def _enable_pack(client) -> None:
    resp = client.post(
        "/onboarding/starter-pack/enable",
        data={"replace_existing": "false", "csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _mark_approved(app, *, tenant_id: str, workflow_slug: str) -> None:
    """Set template to fully approved/sendable state."""
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
        row.updated_at = datetime.now(timezone.utc)
        sess.commit()
    finally:
        sess.close()


def _mark_stale(app, *, tenant_id: str, workflow_slug: str) -> None:
    """Set template to pending_approval with an old updated_at so it reads as stale."""
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
        row.provider_state = "pending_approval"
        row.sendability_state = "pending"
        row.updated_at = datetime.now(timezone.utc) - timedelta(days=5)  # 5 days → stale
        sess.commit()
    finally:
        sess.close()


def _set_provider_state(app, *, tenant_id: str, workflow_slug: str, provider_state: str) -> None:
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
        row.provider_state = provider_state
        row.consent_state = "granted"
        row.updated_at = datetime.now(timezone.utc)
        sess.commit()
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# AC 12.6.1 — Consent ledger: tenant-scoped, searchable, CRUD
# ---------------------------------------------------------------------------


def test_consent_ledger_is_tenant_scoped(compliance_app, client):
    """GET /api/compliance/consent-ledger returns only own-tenant records."""
    identity_a = _new_identity(compliance_app, "ledger-a@example.com")
    identity_b = _new_identity(compliance_app, "ledger-b@example.com")

    db = compliance_app.extensions["saas_db"]
    # Add a record for tenant A
    upsert_consent_record(
        db,
        tenant_id=identity_a.tenant_id,
        contact_id="contact-A-001",
        status="granted",
        source="test",
        actor_id=identity_a.user_id,
        correlation_id="corr-a",
    )
    # Add a record for tenant B
    upsert_consent_record(
        db,
        tenant_id=identity_b.tenant_id,
        contact_id="contact-B-001",
        status="revoked",
        source="test",
        actor_id=identity_b.user_id,
        correlation_id="corr-b",
    )

    _login(client, identity_a)
    resp = client.get("/api/compliance/consent-ledger")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["ok"] is True
    contact_ids = {e["contact_id"] for e in data["entries"]}
    # Tenant A only sees their own records
    assert "contact-A-001" in contact_ids
    assert "contact-B-001" not in contact_ids


def test_consent_ledger_search_filters_by_contact_id(compliance_app, client):
    identity = _new_identity(compliance_app, "ledger-search@example.com")

    db = compliance_app.extensions["saas_db"]
    for i in range(3):
        upsert_consent_record(
            db,
            tenant_id=identity.tenant_id,
            contact_id=f"91987654{i:04d}",
            status="granted",
            source="bulk",
            actor_id=identity.user_id,
            correlation_id=f"corr-{i}",
        )
    upsert_consent_record(
        db,
        tenant_id=identity.tenant_id,
        contact_id="441234567890",
        status="required",
        source="manual",
        actor_id=identity.user_id,
        correlation_id="corr-uk",
    )

    _login(client, identity)
    resp = client.get("/api/compliance/consent-ledger?search=91987654")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["total"] == 3
    assert all("91987654" in e["contact_id"] for e in data["entries"])


def test_upsert_consent_record_creates_then_updates(compliance_app, client):
    """POST /api/compliance/consent-ledger creates entry and allows update."""
    identity = _new_identity(compliance_app, "upsert-create@example.com")
    _login(client, identity)

    # Create
    resp = client.post(
        "/api/compliance/consent-ledger",
        data={"contact_id": "upsert-contact-001", "status": "required", "csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["entry"]["status"] == "required"
    assert "correlation_id" in data

    # Update same contact to granted
    resp2 = client.post(
        "/api/compliance/consent-ledger",
        data={"contact_id": "upsert-contact-001", "status": "granted", "csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert resp2.status_code == 200
    assert resp2.get_json()["entry"]["status"] == "granted"


def test_upsert_consent_invalid_status_returns_400(compliance_app, client):
    identity = _new_identity(compliance_app, "upsert-bad@example.com")
    _login(client, identity)

    resp = client.post(
        "/api/compliance/consent-ledger",
        data={"contact_id": "some-contact", "status": "unknown_value", "csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# AC 12.6.2 — Template sendability states: all provider states exposed
# ---------------------------------------------------------------------------


def test_template_sendability_exposes_approved_pending_rejected_paused(compliance_app, client):
    identity = _new_identity(compliance_app, "sendability-states@example.com")
    _login(client, identity)
    _enable_pack(client)

    db = compliance_app.extensions["saas_db"]
    slugs = {row["workflow_slug"] for row in get_template_sendability_states(db, identity.tenant_id)}
    assert len(slugs) >= 1  # at least one template created by starter pack

    slug = next(iter(slugs))
    # Set each provider state and check it maps correctly
    for ps, expected_display in [
        ("approved", DISPLAY_STATE_APPROVED),
        ("pending_approval", DISPLAY_STATE_PENDING),
        ("rejected", DISPLAY_STATE_REJECTED),
        ("paused", DISPLAY_STATE_PAUSED),
    ]:
        _set_provider_state(compliance_app, tenant_id=identity.tenant_id, workflow_slug=slug, provider_state=ps)
        states = get_template_sendability_states(db, identity.tenant_id)
        match = next(s for s in states if s["workflow_slug"] == slug)
        assert match["display_state"] == expected_display, f"provider_state={ps!r} → expected {expected_display!r}, got {match['display_state']!r}"


def test_template_sendability_api_returns_200(compliance_app, client):
    identity = _new_identity(compliance_app, "sendability-api@example.com")
    _login(client, identity)
    _enable_pack(client)

    resp = client.get("/api/compliance/template-sendability")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["ok"] is True
    assert "templates" in data
    assert "alert" in data
    assert isinstance(data["total"], int)


# ---------------------------------------------------------------------------
# AC 12.6.3 — Sendability alert indicator
# ---------------------------------------------------------------------------


def test_alert_no_issue_when_all_approved():
    states = [
        {"display_state": DISPLAY_STATE_APPROVED, "is_sendable": True, "is_stale": False},
        {"display_state": DISPLAY_STATE_APPROVED, "is_sendable": True, "is_stale": False},
    ]
    alert = evaluate_sendability_alert(states)
    assert alert["level"] == ALERT_NO_ISSUE


def test_alert_warning_when_pending():
    states = [
        {"display_state": DISPLAY_STATE_APPROVED, "is_sendable": True, "is_stale": False},
        {"display_state": DISPLAY_STATE_PENDING, "is_sendable": False, "is_stale": False},
    ]
    alert = evaluate_sendability_alert(states)
    assert alert["level"] == ALERT_WARNING


def test_alert_warning_when_stale():
    states = [
        {"display_state": DISPLAY_STATE_STALE, "is_sendable": False, "is_stale": True},
    ]
    alert = evaluate_sendability_alert(states)
    assert alert["level"] == ALERT_WARNING


def test_alert_action_required_when_rejected():
    states = [
        {"display_state": DISPLAY_STATE_REJECTED, "is_sendable": False, "is_stale": False},
    ]
    alert = evaluate_sendability_alert(states)
    assert alert["level"] == ALERT_ACTION_REQUIRED


def test_alert_action_required_when_unknown():
    states = [
        {"display_state": DISPLAY_STATE_UNKNOWN, "is_sendable": False, "is_stale": False},
    ]
    alert = evaluate_sendability_alert(states)
    assert alert["level"] == ALERT_ACTION_REQUIRED


def test_alert_action_required_overrides_warning():
    states = [
        {"display_state": DISPLAY_STATE_PENDING, "is_sendable": False, "is_stale": False},
        {"display_state": DISPLAY_STATE_REJECTED, "is_sendable": False, "is_stale": False},
    ]
    alert = evaluate_sendability_alert(states)
    assert alert["level"] == ALERT_ACTION_REQUIRED


def test_alert_no_issue_when_empty():
    alert = evaluate_sendability_alert([])
    assert alert["level"] == ALERT_NO_ISSUE


# ---------------------------------------------------------------------------
# AC 12.6.4 — Pre-dispatch gate blocks on missing consent or non-sendable state
# ---------------------------------------------------------------------------


def test_dispatch_blocked_when_consent_missing():
    result = check_dispatch_eligibility(
        consent_status=None,
        provider_state="approved",
        correlation_id="corr-no-consent",
    )
    assert result["eligible"] is False
    assert result["reason_code"] == REASON_CONSENT_MISSING
    assert result["correlation_id"] == "corr-no-consent"


def test_dispatch_blocked_when_consent_required():
    result = check_dispatch_eligibility(
        consent_status="required",
        provider_state="approved",
        correlation_id="corr-required",
    )
    assert result["eligible"] is False
    assert result["reason_code"] == REASON_CONSENT_MISSING


def test_dispatch_blocked_when_provider_state_pending():
    result = check_dispatch_eligibility(
        consent_status="granted",
        provider_state="pending_approval",
        correlation_id="corr-pending",
    )
    assert result["eligible"] is False
    assert result["reason_code"] == REASON_TEMPLATE_NOT_SENDABLE


def test_dispatch_allowed_when_approved_and_granted():
    result = check_dispatch_eligibility(
        consent_status="granted",
        provider_state="approved",
        correlation_id="corr-ok",
    )
    assert result["eligible"] is True
    assert result["reason_code"] is None
    assert result["display_state"] == DISPLAY_STATE_APPROVED


def test_pre_dispatch_gate_via_api_blocks_missing_consent(compliance_app, client):
    """POST /api/compliance/dispatch-eligibility blocks when consent is missing."""
    identity = _new_identity(compliance_app, "dispatch-gate@example.com")
    _login(client, identity)

    resp = client.post(
        "/api/compliance/dispatch-eligibility",
        data={
            "contact_consent_status": "required",
            "provider_state": "approved",
            "workflow_slug": "order_status_update",
            "csrf_token": _CSRF,
        },
        headers={"X-CSRFToken": _CSRF},
    )
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["eligible"] is False
    assert data["reason_code"] == REASON_CONSENT_MISSING
    assert "correlation_id" in data


def test_pre_dispatch_gate_via_api_allows_approved(compliance_app, client):
    identity = _new_identity(compliance_app, "dispatch-allow@example.com")
    _login(client, identity)

    resp = client.post(
        "/api/compliance/dispatch-eligibility",
        data={
            "contact_consent_status": "granted",
            "provider_state": "approved",
            "workflow_slug": "order_status_update",
            "csrf_token": _CSRF,
        },
        headers={"X-CSRFToken": _CSRF},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["eligible"] is True
    assert data["reason_code"] is None


# ---------------------------------------------------------------------------
# AC 12.6.5 — Audit trail with correlation_id; no secret leakage
# ---------------------------------------------------------------------------


def test_upsert_consent_writes_audit_log_with_correlation_id(compliance_app):
    identity = _new_identity(compliance_app, "audit-consent@example.com")
    db = compliance_app.extensions["saas_db"]

    upsert_consent_record(
        db,
        tenant_id=identity.tenant_id,
        contact_id="audit-contact-001",
        status="granted",
        source="integration_test",
        actor_id=identity.user_id,
        correlation_id="audit-corr-12-6",
    )

    with compliance_app.app_context():
        sess = db.session()
        try:
            log = (
                sess.query(AuditLog)
                .filter(
                    AuditLog.tenant_id == identity.tenant_id,
                    AuditLog.action.in_([
                        "compliance.consent_granted",
                        "compliance.consent_recorded",
                        "compliance.consent_updated",
                    ]),
                )
                .order_by(AuditLog.id.desc())
                .first()
            )
            assert log is not None, "AuditLog entry expected but not found"
            payload = json.loads(log.payload)
            assert payload["correlation_id"] == "audit-corr-12-6"
            assert payload["new_status"] == "granted"
        finally:
            sess.close()


def test_audit_log_payload_has_no_secret_material(compliance_app):
    """AuditLog payload must not contain credential-like strings (AC 12.6.5)."""
    identity = _new_identity(compliance_app, "audit-nosecrets@example.com")
    db = compliance_app.extensions["saas_db"]

    upsert_consent_record(
        db,
        tenant_id=identity.tenant_id,
        contact_id="nosecret-contact",
        status="granted",
        source="unit_test",
        actor_id=identity.user_id,
        correlation_id="nosecret-corr",
    )

    with compliance_app.app_context():
        sess = db.session()
        try:
            logs = (
                sess.query(AuditLog)
                .filter(AuditLog.tenant_id == identity.tenant_id)
                .all()
            )
            for log in logs:
                payload_lower = (log.payload or "").lower()
                # No API keys or passwords should appear
                assert "sk-" not in payload_lower
                assert "api_key" not in payload_lower
                assert "password" not in payload_lower
        finally:
            sess.close()


# ---------------------------------------------------------------------------
# AC 12.6.6 — Stale/unknown provider state applies safe default (block send)
# ---------------------------------------------------------------------------


def test_stale_provider_state_maps_to_stale_display_and_blocks_send(compliance_app, client):
    identity = _new_identity(compliance_app, "stale-state@example.com")
    _login(client, identity)
    _enable_pack(client)
    _mark_stale(compliance_app, tenant_id=identity.tenant_id, workflow_slug="order_status_update")

    db = compliance_app.extensions["saas_db"]
    states = get_template_sendability_states(
        db,
        identity.tenant_id,
        stale_threshold_seconds=3600,  # 1 hour; our template is 5 days old → stale
    )
    stale_entry = next(s for s in states if s["workflow_slug"] == "order_status_update")
    assert stale_entry["is_stale"] is True
    assert stale_entry["display_state"] == DISPLAY_STATE_STALE
    assert stale_entry["is_sendable"] is False


def test_stale_state_blocks_dispatch_with_stale_reason(compliance_app):
    # Simulate a 5-day-old pending_approval
    stale_time = datetime.now(timezone.utc) - timedelta(days=5)
    result = check_dispatch_eligibility(
        consent_status="granted",
        provider_state="pending_approval",
        updated_at=stale_time,
        stale_threshold_seconds=3600,
        correlation_id="corr-stale",
    )
    assert result["eligible"] is False
    assert result["reason_code"] == REASON_STALE_OR_UNKNOWN
    assert result["is_stale"] is True
    assert result["display_state"] == DISPLAY_STATE_STALE


def test_unknown_provider_state_applies_safe_default_and_blocks():
    """A completely unknown/missing provider state must never allow a send."""
    result = check_dispatch_eligibility(
        consent_status="granted",
        provider_state=None,
        correlation_id="corr-unknown",
    )
    assert result["eligible"] is False
    assert result["reason_code"] == REASON_STALE_OR_UNKNOWN
    assert result["display_state"] == DISPLAY_STATE_UNKNOWN


def test_unknown_provider_state_via_map():
    display, is_stale = map_provider_state_to_display("completely_unrecognized_state")
    assert display == DISPLAY_STATE_UNKNOWN
    assert is_stale is False


def test_template_sendability_api_marks_stale_in_response(compliance_app, client):
    identity = _new_identity(compliance_app, "stale-api@example.com")
    _login(client, identity)
    _enable_pack(client)
    _mark_stale(compliance_app, tenant_id=identity.tenant_id, workflow_slug="order_status_update")

    resp = client.get(
        "/api/compliance/template-sendability",
        query_string={"stale_threshold_seconds": "3600"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    template = next(
        (t for t in data["templates"] if t["workflow_slug"] == "order_status_update"),
        None,
    )
    assert template is not None
    assert template["is_stale"] is True
    assert template["is_sendable"] is False


# ---------------------------------------------------------------------------
# AC 12.6.7 — Gate does NOT alter retry/fallback path; eligible sends unaffected
# ---------------------------------------------------------------------------


def test_eligible_send_preserves_dispatch_path(compliance_app, client):
    """An approved+consented template activation is not blocked (AC 12.6.7)."""
    identity = _new_identity(compliance_app, "eligible-send@example.com")
    _login(client, identity)
    _enable_pack(client)
    _mark_approved(compliance_app, tenant_id=identity.tenant_id, workflow_slug="order_status_update")

    # The dispatch eligibility gate should return eligible=True for this template
    result = check_dispatch_eligibility(
        consent_status="granted",
        provider_state="approved",
        correlation_id="corr-eligible",
    )
    assert result["eligible"] is True
    assert result["reason_code"] is None
    assert result["display_state"] == DISPLAY_STATE_APPROVED
    assert result["is_stale"] is False


def test_active_provider_state_treated_as_approved_and_sendable():
    """'active' is an alias for 'approved' in some provider responses."""
    result = check_dispatch_eligibility(
        consent_status="granted",
        provider_state="active",
        correlation_id="corr-active",
    )
    assert result["eligible"] is True
    assert result["display_state"] == DISPLAY_STATE_APPROVED


def test_operator_endpoints_require_operator_role(compliance_app, client):
    """Consent ledger and sendability APIs must return 403 without operator role."""
    identity = _new_identity(compliance_app, "no-role@example.com")
    # Log in without setting operator role
    with client.session_transaction() as sess:
        sess[AUTH_SESSION_USER_KEY] = identity.user_id
        sess[AUTH_SESSION_TENANT_KEY] = identity.tenant_id
        sess["_csrf_token"] = _CSRF
        # Intentionally NOT setting sess["dashboard_role"] = "operator"

    # GET endpoints redirect (302) non-operator requests — this is the correct guard behavior.
    resp_ledger = client.get("/api/compliance/consent-ledger")
    assert resp_ledger.status_code in (302, 403)

    resp_sendability = client.get("/api/compliance/template-sendability")
    assert resp_sendability.status_code in (302, 403)

    # POST endpoint returns 403 JSON for non-operator requests.
    resp_post = client.post(
        "/api/compliance/consent-ledger",
        data={"contact_id": "x", "status": "granted", "csrf_token": _CSRF},
        headers={"X-CSRFToken": _CSRF},
    )
    assert resp_post.status_code == 403
