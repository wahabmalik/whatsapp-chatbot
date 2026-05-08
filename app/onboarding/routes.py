"""Onboarding routes for tenant SaaS flow.

Implements:
- GET /onboarding: Onboarding page
- GET /onboarding/qr-code: QR code API endpoint
- GET /onboarding/status-stream: SSE connection status stream
"""

from __future__ import annotations

import time

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, session, stream_with_context, url_for

from app.services.auth_service import current_identity
from .service import (
    EvolutionUnavailableError,
    EvolutionResponseValidationError,
    NoActiveSubscriptionError,
    get_or_create_qr_code,
    sse_event,
    sync_connection_status,
)


onboarding_blueprint = Blueprint("onboarding", __name__)


def _require_auth():
    """Guard: redirect to login if not authenticated."""
    if current_identity(session) is None:
        return redirect(url_for("auth.login"))
    return None


@onboarding_blueprint.get("/onboarding")
def onboarding_page():
    """Render onboarding page for authenticated user."""
    guarded = _require_auth()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    if identity is None:
        return redirect(url_for("auth.login"))

    return render_template("onboarding.html", page_key="onboarding", nav_mode="user")


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

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

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

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return jsonify({"ok": False, "error_code": "SAAS_UNAVAILABLE", "message": "SaaS database is not configured."}), 503

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
