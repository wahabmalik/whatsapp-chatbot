"""Onboarding routes for tenant SaaS flow.

Implements:
- GET /onboarding: Onboarding page
- GET /onboarding/qr-code: QR code API endpoint
- GET /onboarding/status-stream: SSE connection status stream
"""

from __future__ import annotations

import hmac
import time

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session, stream_with_context, url_for

from app.services.auth_service import current_identity
from app.services.starter_pack import (
    CATEGORY_EXPLAINER_URL,
    STARTER_PACK_COHORT_SLICE,
    STARTER_PACK_KEY,
    STARTER_PACK_LABEL,
    activate_starter_draft,
    enable_starter_pack,
    is_starter_pack_enabled_for_tenant,
    list_tenant_starter_drafts,
    submit_starter_draft,
    update_tenant_starter_draft,
)
from .service import (
    EvolutionUnavailableError,
    EvolutionResponseValidationError,
    NoActiveSubscriptionError,
    get_or_create_qr_code,
    sse_event,
    sync_connection_status,
)


onboarding_blueprint = Blueprint("onboarding", __name__)
_CSRF_SESSION_KEY = "_csrf_token"


def _require_auth():
    """Guard: redirect to login if not authenticated."""
    if current_identity(session) is None:
        return redirect(url_for("auth.login"))
    return None


def _validate_csrf_token() -> bool:
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        return False
    submitted = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
    return hmac.compare_digest(str(token), str(submitted))


def _starter_pack_context(tenant_id: str) -> dict:
    enabled = is_starter_pack_enabled_for_tenant(current_app, tenant_id)
    drafts = list_tenant_starter_drafts(current_app.extensions["saas_db"], tenant_id) if enabled else []
    return {
        "starter_pack_visible": enabled,
        "starter_pack_key": STARTER_PACK_KEY,
        "starter_pack_label": STARTER_PACK_LABEL,
        "starter_pack_cohort": STARTER_PACK_COHORT_SLICE,
        "starter_pack_category_explainer_url": CATEGORY_EXPLAINER_URL,
        "starter_pack_drafts": drafts,
    }


def _require_starter_pack_eligibility(tenant_id: str):
    if is_starter_pack_enabled_for_tenant(current_app, tenant_id):
        return None
    return jsonify({"ok": False, "message": "India D2C starter pack is not enabled for this tenant cohort."}), 404


def _db_or_503():
    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return None, (jsonify({"ok": False, "message": "SaaS database is not configured."}), 503)
    return db, None


def _request_bool(name: str) -> bool:
    raw = request.form.get(name)
    if raw is None and request.is_json:
        payload = request.get_json(silent=True) or {}
        raw = payload.get(name)
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _request_value(name: str) -> str | None:
    raw = request.form.get(name)
    if raw is None and request.is_json:
        payload = request.get_json(silent=True) or {}
        raw = payload.get(name)
    if raw is None:
        return None
    return str(raw)


@onboarding_blueprint.get("/onboarding")
def onboarding_page():
    """Render onboarding page for authenticated user."""
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return redirect(url_for("auth.login"))

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    return render_template(
        "onboarding.html",
        page_key="onboarding",
        nav_mode="user",
        **_starter_pack_context(identity.tenant_id),
    )


@onboarding_blueprint.get("/onboarding/qr-code")
def onboarding_qr_code():
    """API: Get or create QR code for tenant.

    Errors:
    - 401: Not authenticated
    - 402: No active subscription
    - 503: Evolution API unavailable or malformed response
    """
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "error_code": "UNAUTHORIZED", "message": "Authentication required."}), 401

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    try:
        qr = get_or_create_qr_code(db, current_app, identity.tenant_id)
    except NoActiveSubscriptionError:
        return jsonify({"ok": False, "error_code": "NO_ACTIVE_SUBSCRIPTION", "message": "Active subscription required."}), 402
    except EvolutionResponseValidationError as exc:
        # Malformed response from Evolution API
        current_app.logger.error(f"Evolution API response validation failed: {exc}")
        return jsonify({
            "ok": False,
            "error_code": "EVOLUTION_RESPONSE_INVALID",
            "message": "Evolution API returned malformed response. Retry shortly.",
        }), 503
    except EvolutionUnavailableError as exc:
        current_app.logger.warning(f"Evolution API unavailable: {exc}")
        return jsonify({
            "ok": False,
            "error_code": "EVOLUTION_UNAVAILABLE",
            "message": "Evolution API unavailable. Retry shortly.",
        }), 503

    return jsonify({
        "ok": True,
        "data": {
            "qr_image": qr.qr_image,
            "expires_in_seconds": qr.expires_in_seconds,
            "instance_name": qr.instance_name,
            "already_connected": qr.already_connected,
            "phone": qr.phone,
        },
        "error": None,
    })


@onboarding_blueprint.get("/onboarding/status-stream")
def onboarding_status_stream():
    """API: Server-Sent Events stream for connection status polling.

    Emits events:
    - status: 'disconnected', 'connecting', or 'connected'
    - phone: (optional) phone number when available
    - retry_after: (on error) suggest retry delay in seconds

    Errors:
    - 401: Not authenticated
    """
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "error_code": "UNAUTHORIZED", "message": "Authentication required."}), 401

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    interval = float(current_app.config.get("ONBOARDING_STATUS_STREAM_INTERVAL_SECONDS", 2.0))
    max_events = max(1, int(current_app.config.get("ONBOARDING_STATUS_STREAM_MAX_EVENTS", 60)))

    @stream_with_context
    def _generate():
        """Generator: emit SSE events until connected or max events."""
        sent = 0
        while sent < max_events:
            sent += 1
            try:
                snapshot = sync_connection_status(db, current_app, identity.tenant_id)
                payload = {"status": snapshot.status}
                if snapshot.phone:
                    payload["phone"] = snapshot.phone
            except (EvolutionUnavailableError, EvolutionResponseValidationError):
                payload = {"status": "error", "retry_after": max(1, int(interval))}

            yield sse_event(payload)

            if payload.get("status") == "connected":
                break
            if interval > 0:
                time.sleep(interval)

    response = Response(_generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@onboarding_blueprint.get("/onboarding/starter-pack/status")
def starter_pack_status():
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "message": "Authentication required."}), 401

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    context = _starter_pack_context(identity.tenant_id)
    return jsonify({"ok": True, **context}), 200


@onboarding_blueprint.post("/onboarding/starter-pack/enable")
def starter_pack_enable():
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "message": "Authentication required."}), 401

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    eligibility_error = _require_starter_pack_eligibility(identity.tenant_id)
    if eligibility_error is not None:
        return eligibility_error

    replace_existing = str(request.form.get("replace_existing", "false")).strip().lower() in {"1", "true", "yes"}
    result = enable_starter_pack(
        db,
        current_app,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        source="onboarding",
        replace_existing=replace_existing,
    )

    if result["summary"]["failed"]:
        return jsonify({"ok": False, **result}), 207

    return jsonify({"ok": True, **result}), 200


@onboarding_blueprint.post("/onboarding/starter-pack/draft/<workflow_slug>/update")
def starter_pack_update_draft(workflow_slug: str):
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "message": "Authentication required."}), 401

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    eligibility_error = _require_starter_pack_eligibility(identity.tenant_id)
    if eligibility_error is not None:
        return eligibility_error

    title = str(request.form.get("title", "")).strip()
    body = str(request.form.get("body", "")).strip()
    category_label = str(request.form.get("category_label", "")).strip().upper()
    if not title or not body or not category_label:
        return jsonify({"ok": False, "message": "title, body, and category_label are required."}), 400

    draft = update_tenant_starter_draft(
        db,
        tenant_id=identity.tenant_id,
        workflow_slug=workflow_slug,
        title=title,
        body=body,
        category_label=category_label,
    )
    if draft is None:
        return jsonify({"ok": False, "message": "Draft not found."}), 404

    return jsonify({"ok": True, "draft": draft}), 200


@onboarding_blueprint.post("/onboarding/starter-pack/draft/<workflow_slug>/submit")
def starter_pack_submit_draft(workflow_slug: str):
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "message": "Authentication required."}), 401

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    eligibility_error = _require_starter_pack_eligibility(identity.tenant_id)
    if eligibility_error is not None:
        return eligibility_error

    draft, blocked_reason = submit_starter_draft(
        db,
        current_app,
        tenant_id=identity.tenant_id,
        workflow_slug=workflow_slug,
        actor_id=identity.user_id,
    )
    if draft is None:
        return jsonify({"ok": False, "message": "Draft not found."}), 404
    if blocked_reason is not None:
        return jsonify({
            "ok": False,
            "message": "Draft submission blocked by consent/approval controls.",
            "blocked_reason": blocked_reason,
            "draft": draft,
        }), 409

    return jsonify({"ok": True, "draft": draft}), 200


@onboarding_blueprint.post("/onboarding/starter-pack/draft/<workflow_slug>/activate")
def starter_pack_activate_draft(workflow_slug: str):
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return jsonify({"ok": False, "message": "Authentication required."}), 401

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    db, error_response = _db_or_503()
    if error_response is not None:
        return error_response

    eligibility_error = _require_starter_pack_eligibility(identity.tenant_id)
    if eligibility_error is not None:
        return eligibility_error

    preview_only = _request_bool("preview_only")
    operator_confirmed = _request_bool("explicit_cost_confirmation")
    recipient_count = _request_value("recipient_count")

    draft, blocked_reason, estimate = activate_starter_draft(
        db,
        current_app,
        tenant_id=identity.tenant_id,
        workflow_slug=workflow_slug,
        actor_id=identity.user_id,
        recipient_count=recipient_count,
        preview_only=preview_only,
        operator_confirmed=operator_confirmed,
    )
    if draft is None:
        return jsonify({"ok": False, "message": "Draft not found."}), 404
    if blocked_reason == "estimation_failed":
        return jsonify({
            "ok": False,
            "message": (estimate or {}).get("estimation_error") or "Could not estimate projected spend. Fix the pricing inputs and retry.",
            "blocked_reason": blocked_reason,
            "draft": draft,
            "estimate": estimate,
        }), 422
    if blocked_reason == "cost_confirmation_required":
        return jsonify({
            "ok": False,
            "message": "Projected spend exceeds the warning threshold. Confirm the estimate to continue.",
            "blocked_reason": blocked_reason,
            "confirmation_required": True,
            "draft": draft,
            "estimate": estimate,
        }), 409
    if blocked_reason is not None:
        return jsonify({
            "ok": False,
            "message": "Draft activation blocked by sendability controls.",
            "blocked_reason": blocked_reason,
            "draft": draft,
            "estimate": estimate,
        }), 409
    if preview_only:
        return jsonify({
            "ok": True,
            "preview_only": True,
            "message": "Projected spend estimate ready.",
            "draft": draft,
            "estimate": estimate,
        }), 200

    return jsonify({"ok": True, "draft": draft, "estimate": estimate}), 200
